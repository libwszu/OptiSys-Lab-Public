"""G3 UI pages (Streamlit).

Each module exposes ``render(ctx)`` and nothing else.  Pages are forbidden from
importing the optical chain or starting processes directly; all access goes
through ``app.ui_context.UiContext``.
"""