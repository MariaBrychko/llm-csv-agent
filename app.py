import hashlib
import json
import tempfile
from pathlib import Path

import streamlit as st

from agent import run_agent
from tools import MAX_BYTES, load_csv_bytes


st.set_page_config(
    page_title="CSV Data Agent",
    page_icon="📋",
    layout="wide"
)

st.markdown(
    """
    <style>
    /* Ширина сторінки та відступи */
    [data-testid="stMainBlockContainer"] {
        max-width: 1120px;
        padding-top: 2.5rem;
        padding-bottom: 2rem;
    }

    /* Бічна панель */
    [data-testid="stSidebar"] {
        border-right: 1px solid #E5DDF0;
    }

    [data-testid="stSidebar"] h3 {
        font-size: 1.05rem;
        font-weight: 600;
        color: #594574;
    }

    /* Заголовки */
    h1 {
        font-size: 2.2rem !important;
        font-weight: 650 !important;
        letter-spacing: -0.06rem;
        color: #493460;
    }

    h2, h3 {
        color: #594574;
        font-weight: 600 !important;
    }

    /* Повідомлення чату */
    [data-testid="stChatMessage"] {
        background: #FFFFFF;
        border: 1px solid #EAE2F3;
        border-radius: 14px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.75rem;
        box-shadow: 0 2px 8px rgba(79, 49, 113, 0.03);
    }

    /* Блоки таблиці та журналу */
    [data-testid="stExpander"] {
        background: #FFFFFF;
        border-radius: 12px;
    }

    /* Кнопки */
    .stButton > button,
    .stDownloadButton > button,
    .stLinkButton > a {
        border-radius: 10px;
        border: 1px solid #DFD3EE;
        font-weight: 500;
        box-shadow: none;
        transition:
            background-color 0.15s ease,
            border-color 0.15s ease;
    }

    .stButton > button:hover,
    .stDownloadButton > button:hover,
    .stLinkButton > a:hover {
        background-color: #F0E8FA;
        border-color: #B798DB;
        color: #694299;
    }

    /* Поле повідомлення */
    [data-testid="stChatInput"] {
        border-radius: 14px;
        box-shadow: 0 3px 14px rgba(79, 49, 113, 0.05);
    }

    /* Мобільний вигляд */
    @media (max-width: 640px) {
        [data-testid="stMainBlockContainer"] {
            padding-top: 1.5rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }

        h1 {
            font-size: 1.75rem !important;
        }

        [data-testid="stChatMessage"] {
            padding: 0.8rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("CSV Data Agent")

st.write(
    "LLM-агент для перевірки й очищення CSV-таблиць. "
    "Знаходить пропуски та дублікати, "
    "обчислює статистику, групує дані "
    "й зберігає результати за вашими вказівками."
)


state = st.session_state

if "folder" not in state:
    state.folder = tempfile.TemporaryDirectory(
        prefix="csv_agent_"
    )

    root = Path(state.folder.name)

    demo = Path(__file__).with_name(
        "demo.csv"
    ).read_bytes()

    (root / "demo.csv").write_bytes(demo)

    state.api_messages = []
    state.chat_messages = []
    state.journal = []
    state.upload_digest = None

root = Path(state.folder.name)


with st.sidebar:
    st.subheader("Налаштування")

    api_key = st.text_input(
        "Groq API-ключ",
        type="password",
        key="llm_key"
    )

    model = st.selectbox(
        "Модель",
        [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b"
        ]
    )

    st.caption(
        "Ключ використовується в поточній сесії "
        "та не записується у файли."
    )

    st.link_button(
        "Отримати Groq API-ключ",
        "https://console.groq.com/keys"
    )

    st.caption(
        "До Groq передаються запити й дані, "
        "які повертають інструменти. "
        "Для демонстрації використовуйте навчальні CSV."
    )

    use_demo = st.radio(
        "Джерело даних",
        [
            "Приклад",
            "Власний CSV"
        ]
    )

    uploaded = None

    if use_demo == "Власний CSV":
        uploaded = st.file_uploader(
            "CSV у UTF-8, до 2 МБ",
            type=["csv"],
            max_upload_size=2
        )

    if st.button("Очистити чат"):
        state.api_messages = []
        state.chat_messages = []
        state.journal = []
        st.rerun()


active_file = "demo.csv"

if use_demo == "Власний CSV":
    if uploaded is None:
        st.info(
            "Завантажте CSV або оберіть приклад "
            "у бічній панелі."
        )
        st.stop()

    raw = uploaded.getvalue()

    try:
        load_csv_bytes(raw)

    except Exception:
        st.error(
            "Не вдалося прочитати CSV. "
            "Потрібен UTF-8, роздільник "
            "кома/крапка з комою/табуляція, "
            "до 2 МБ, 10 000 рядків і 50 стовпців."
        )
        st.stop()

    digest = hashlib.sha256(raw).hexdigest()

    if digest != state.upload_digest:
        for file in root.iterdir():
            if (
                file.is_file()
                and file.name != "demo.csv"
            ):
                file.unlink()

        (root / "data.csv").write_bytes(raw)

        state.upload_digest = digest
        state.api_messages = []
        state.chat_messages = []
        state.journal = []

    active_file = "data.csv"


st.caption(
    f"Поточний файл: {active_file}. "
    "Результати сесії тимчасові — "
    "скачайте потрібні файли."
)

with st.expander(
    "Перегляд вхідної таблиці",
    expanded=True
):
    frame = load_csv_bytes(
        (root / active_file).read_bytes()
    )

    st.dataframe(
        frame.head(20),
        hide_index=True,
        width="stretch",
        height=280
    )

st.caption(
    "Приклад запиту: Перевір поточний CSV: "
    "скільки в ньому рядків, пропусків "
    "і повних дублікатів?"
)


for message in state.chat_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


prompt = st.chat_input(
    "Що зробити з таблицею?",
    disabled=not bool(api_key.strip()),
    max_chars=2000
)

if not api_key.strip():
    st.info(
        "Введіть Groq API-ключ у бічній панелі, "
        "щоб почати діалог."
    )

if prompt:
    state.chat_messages.append({
        "role": "user",
        "content": prompt
    })

    state.api_messages.append({
        "role": "user",
        "content": prompt
    })

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Агент виконує запит…"):
            try:
                answer = run_agent(
                    api_key.strip(),
                    model,
                    state.api_messages,
                    root,
                    active_file,
                    state.journal
                )

            except Exception as error:
                answer = (
                    f"Запит зупинено: {error} "
                    "Перевірте журнал виконаних дій."
                )

                state.api_messages.append({
                    "role": "assistant",
                    "content": answer
                })

        st.markdown(answer)

    state.chat_messages.append({
        "role": "assistant",
        "content": answer
    })


with st.expander("Журнал інструментів"):
    if state.journal:
        st.json(state.journal)

        st.download_button(
            "Скачати журнал JSON",

            json.dumps(
                state.journal,
                ensure_ascii=False,
                indent=2
            ),

            file_name="tool_journal.json",
            mime="application/json"
        )

    else:
        st.caption(
            "Поки немає викликів інструментів."
        )


st.subheader("Файли сесії")

for file in sorted(root.iterdir()):
    if (
        file.is_file()
        and file.stat().st_size <= MAX_BYTES
    ):
        st.download_button(
            f"Скачати {file.name}",
            file.read_bytes(),
            file_name=file.name,
            key=f"download_{file.name}"
        )