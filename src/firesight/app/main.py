"""
FireSight demo UI.

    uv run streamlit run src/firesight/app/main.py

A READ-ONLY consumer of the measured modules. It calls the router, the SQL
agent, the vector store and the synthesiser; it changes none of them. Every
figure published in the README was produced by that code, so altering it from
here would quietly invalidate the numbers. `tests/test_measured_surface.py`
enforces this with content hashes.

The internals panel is the point of the demo. Anyone can show a chatbot
answering a question; the interesting part is the route it chose and why, the
SQL it actually executed, the chunks it retrieved with their scores, and what
the query cost.

LOCAL ONLY. Every question is a live API call billed to whoever's key is in
.env. Do not host this.
"""

from __future__ import annotations

import os
import time

import streamlit as st

from firesight.config import settings
from firesight.generation.answer import answer as run_answer
from firesight.generation.llm import available as llm_available
from firesight.generation.llm import redact
from firesight.retrieval.router import ExclusionReason, Route
from firesight.retrieval.vector_store import search

# Per-session spend guard, separate from the evaluation cap. Every typed
# question is a live billed call and someone else will be driving this.
DEFAULT_SESSION_BUDGET_USD = float(os.getenv("FIRESIGHT_APP_BUDGET_USD", "1.00"))

FINDINGS_LINK = (
    "https://github.com/karimmorgan/firesight-rag"
    "#1-the-system-reproduced-this-projects-own-tie-handling-error-in-the-opposite-direction"
)

EXAMPLES: list[tuple[str, str]] = [
    ("structured", "What was Sewanee's P90 response time in 2024?"),
    ("structured", "Which five peer departments in Tennessee had the fastest P90 response times?"),
    ("unstructured", "How does NFIRS define a structure fire?"),
    ("unstructured", "Which NFIRS module is completed for wildland fires?"),
    ("hybrid", "How many structure fires did we have in 2024, and how does NFIRS define one?"),
    ("hybrid", "How do we compare to peers on response time, and what makes "
               "the peer cohort not a random sample?"),
    ("out_of_scope", "What is the recommended pressure for a fire sprinkler system under NFPA 13?"),
    ("percentile", "How does Sewanee's P90 response time rank against its peer departments?"),
]

ROUTE_COLOUR = {
    Route.STRUCTURED: "blue",
    Route.UNSTRUCTURED: "green",
    Route.HYBRID: "violet",
    Route.OUT_OF_SCOPE: "orange",
}


@st.cache_resource(show_spinner="Loading the embedding model (first start only)…")
def warm_models() -> bool:
    """
    Load the sentence-transformer once at startup instead of inside the first
    question.

    Measured: a cold first query blocks for ~41s while the model loads, and a
    block that long can drop the browser session before the answer renders --
    the result arrives into a session that no longer exists. Warming moves the
    wait to app start, where a spinner explains it.

    This only CALLS the measured retrieval path; it changes nothing in it.
    """
    try:
        search("warmup", k=1)
    except Exception:  # noqa: BLE001 - a cold cache is not worth failing over
        return False
    return True


def init_state() -> None:
    st.session_state.setdefault("spend", 0.0)
    st.session_state.setdefault("queries", 0)
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("rerank_latency", {})


def budget_remaining(limit: float) -> float:
    return max(0.0, limit - st.session_state.spend)


def render_spend(spend_slot, bar_slot, caption_slot, limit: float) -> None:
    """Draw the spend guard. Called before and again after each query."""
    spent = st.session_state.spend
    spend_slot.metric("Spent this session", f"${spent:.4f}")
    bar_slot.progress(min(1.0, spent / limit) if limit else 1.0)
    caption_slot.caption(
        f"{st.session_state.queries} queries · ${budget_remaining(limit):.4f} left"
    )


def render_internals(res, rerank_on: bool) -> None:
    """The expandable panel. This is what demonstrates the engineering."""
    d = res.routing.decision

    with st.expander("Inside this answer", expanded=True):
        # ── route ──────────────────────────────────────────────────────
        st.markdown("**Route**")
        if d is None:
            st.warning(f"The router could not classify this question: {res.routing.error}")
        else:
            colour = ROUTE_COLOUR.get(d.route, "gray")
            st.markdown(
                f":{colour}[**{d.route.value}**] &nbsp; "
                f"confidence **{d.confidence:.2f}**"
            )
            st.caption(f"Router's reason: {d.reason}")
            if d.exclusion_reason is not ExclusionReason.NONE:
                st.markdown(
                    f"Refused because: `{d.exclusion_reason.value}` — the answer "
                    "lies in material this corpus deliberately excludes."
                )

        # ── SQL, exactly as executed ───────────────────────────────────
        if res.sql:
            st.markdown("**SQL executed** — this is the citation for a structured answer")
            st.code(res.sql, language="sql")

        # ── retrieved chunks ───────────────────────────────────────────
        if res.hits:
            is_scope = d is not None and d.route is Route.OUT_OF_SCOPE
            st.markdown(
                "**Scope boundary cited**" if is_scope else "**Chunks retrieved**"
            )
            if is_scope:
                st.caption(
                    "Fetched by name, not by ranking. Measured: the scope document "
                    "does not reach the top 5 for this question — the same "
                    "similarity blindness that lets it past the support floor."
                )
            for h in res.hits:
                score_label = "cross-encoder" if rerank_on else "cosine"
                st.markdown(
                    f"`{h.score:.3f}` *{score_label}* &nbsp;·&nbsp; "
                    f"**{h.source_document}** — {h.section}"
                    + (f" (p. {h.page})" if h.page else "")
                )
                st.caption(h.text[:280] + ("…" if len(h.text) > 280 else ""))

        # ── citations ──────────────────────────────────────────────────
        if res.citations:
            kinds = ", ".join(sorted(res.citation_kinds))
            st.markdown(f"**Citations** ({kinds})")
            for c in res.citations:
                if c.kind == "sql":
                    st.markdown("- `[sql]` the query above")
                else:
                    st.markdown(f"- `[{c.kind}]` {c.text}")

        # ── cost of this query ─────────────────────────────────────────
        st.markdown("**This query**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Latency", f"{res.latency_ms / 1000:.1f} s")
        c2.metric("Tokens in", f"{res.input_tokens:,}")
        c3.metric("Tokens out", f"{res.output_tokens:,}")
        c4.metric("Cost", f"${res.cost_usd:.5f}")


def main() -> None:
    st.set_page_config(page_title="FireSight RAG", page_icon="🚒", layout="wide")
    init_state()

    st.title("FireSight")
    st.caption(
        "Hybrid retrieval over NFIRS fire-service data — routed to SQL, to "
        "documents, to both, or refused with a citation."
    )

    # ── permanent caveats, in the UI and not only the README ───────────
    st.warning(
        "**Read these before trusting a number.** The benchmarkable cohort is "
        "the **~37% of departments that file complete administrative data** — a "
        "selection effect, not a random sample, and departments diligent about "
        "paperwork plausibly differ from those that are not. All response-time "
        "figures are **CY2024 alarm-to-arrival only**: NFIRS records no dispatch "
        "or en-route timestamp, so turnout and travel time cannot be computed "
        "from it for any department in any year.",
        icon="⚠️",
    )

    with st.sidebar:
        st.subheader("Session")
        limit = st.number_input(
            "Spend limit for this session (USD)",
            min_value=0.05,
            max_value=20.0,
            value=DEFAULT_SESSION_BUDGET_USD,
            step=0.25,
            help="Hard stop. Every question is a live billed API call.",
        )
        # Placeholders, filled again after the query runs. Streamlit renders
        # top-to-bottom, so a spend counter written here would show the value
        # from BEFORE the query that is about to be billed -- a spend guard
        # that lags by one query is worse than none.
        spend_slot = st.empty()
        bar_slot = st.empty()
        caption_slot = st.empty()
        render_spend(spend_slot, bar_slot, caption_slot, limit)

        st.divider()
        st.subheader("Retrieval")
        rerank_on = st.toggle(
            "Cross-encoder rerank",
            value=False,
            help="Off by default. See the note below.",
        )
        st.caption(
            "**Not established at n=50.** Paired sign test p=0.064 (small) and "
            "p=0.230 (default); the n=15 estimate overstated the effect 2–4×. "
            "It costs roughly 90× the latency, so it ships off."
        )
        lat = st.session_state.rerank_latency
        if lat.get(False) and lat.get(True):
            st.caption(
                f"Measured here: **{lat[False]:.0f} ms** off vs "
                f"**{lat[True]:.0f} ms** on."
            )
        elif lat:
            which = "on" if True in lat else "off"
            st.caption(f"Measured here with rerank {which}: {list(lat.values())[0]:.0f} ms. "
                       "Toggle and ask again to see the delta.")

        st.divider()
        st.caption(
            f"Model `{settings.llm_model}` · embeddings `{settings.embed_model}` · "
            "local only, do not host."
        )

    warm_models()

    if not llm_available():
        st.error(
            "No API key configured. Put `ANTHROPIC_API_KEY=...` in `.env` and "
            "restart. The key is read from the environment by the SDK; this app "
            "never reads, displays or stores it."
        )
        st.stop()

    # ── examples ───────────────────────────────────────────────────────
    st.markdown("**Try one** — these cover all four routes")
    cols = st.columns(4)
    for i, (kind, q) in enumerate(EXAMPLES):
        if cols[i % 4].button(q, key=f"ex{i}", help=f"expected route: {kind}",
                              use_container_width=True):
            st.session_state.pending = q
    st.caption(
        "The NFPA 13 question is refused *with a citation* — the corpus excludes "
        "copyrighted standards, and similarity search cannot tell that question "
        "apart from an answerable one. The percentile question reproduces a "
        "**documented defect**: the model returns a rank rather than a "
        "percentile. It is left unfixed so the demo matches the measurements — "
        f"see [the findings section]({FINDINGS_LINK})."
    )

    typed = st.chat_input("Ask about fire department performance, NFIRS, or this project's method")
    question = typed or st.session_state.pending
    st.session_state.pending = None

    for past in st.session_state.history:
        with st.chat_message(past["role"]):
            st.markdown(past["content"])

    if not question:
        return

    if not question.strip():
        st.info("Type a question first.")
        return
    if len(question) > 2000:
        st.info("That question is very long — please shorten it to under 2,000 characters.")
        return

    if budget_remaining(limit) <= 0:
        st.error(
            f"**Session spend limit reached** (${limit:.2f}). "
            f"${st.session_state.spend:.4f} spent across "
            f"{st.session_state.queries} queries. Raise the limit in the sidebar "
            "or restart the app to continue."
        )
        return

    with st.chat_message("user"):
        st.markdown(question)
    st.session_state.history.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("_Routing…_")
        t0 = time.perf_counter()
        try:
            with st.spinner("Routing, retrieving and answering…"):
                res = run_answer(question, rerank=rerank_on)
        except Exception as exc:  # noqa: BLE001 - never surface a traceback
            placeholder.empty()
            st.error(
                "Something went wrong answering that. Details: "
                f"{redact(str(exc))[:400]}"
            )
            st.session_state.history.append(
                {"role": "assistant", "content": "_(failed)_"}
            )
            return

        elapsed_ms = (time.perf_counter() - t0) * 1000
        st.session_state.rerank_latency[rerank_on] = elapsed_ms
        st.session_state.spend += res.cost_usd
        st.session_state.queries += 1
        # Repaint the sidebar now that this query has been billed.
        render_spend(spend_slot, bar_slot, caption_slot, limit)

        # Stream the answer a word at a time so it reads as a response rather
        # than appearing all at once.
        shown = ""
        for word in res.text.split(" "):
            shown += word + " "
            placeholder.markdown(shown)
            time.sleep(0.012)
        placeholder.markdown(res.text)

        if not res.answered:
            st.info(
                "This was **refused**, not failed. The expander below shows which "
                "scope boundary it hit and the section cited for it."
            )

        render_internals(res, rerank_on)

    st.session_state.history.append({"role": "assistant", "content": res.text})

    if budget_remaining(limit) <= 0:
        st.warning(
            f"That query reached the ${limit:.2f} session limit. Further "
            "questions are blocked until the limit is raised or the app restarted."
        )


if __name__ == "__main__":
    main()
