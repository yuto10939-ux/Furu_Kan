import streamlit as st
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore
from PIL import Image
import uuid
import datetime
import os

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Furu_Kan - Vintage Levi's Appraiser",
    page_icon="👖",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- CUSTOM CSS (Chic, Dark Theme) ---
st.markdown("""
<style>
    /* Main Background & Text */
    .stApp {
        background-color: #FFFFFF;
        color: #333333;
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
    
    /* Hide Streamlit Branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Headers */
    h1, h2, h3 {
        color: #121212;
        font-weight: 300;
        letter-spacing: 1.5px;
    }
    
    /* Chat Messages */
    .stChatMessage {
        background-color: transparent !important;
        border: none !important;
        padding: 1rem 0 !important;
    }
    .stChatMessage [data-testid="chatAvatarIcon-user"] {
        background-color: #4A4A4A;
    }
    .stChatMessage [data-testid="chatAvatarIcon-assistant"] {
        background-color: #1E3A8A; /* Denim Blue */
    }
    
    /* Upload Button */
    .stFileUploader > div > div > div > button {
        background-color: #1E3A8A !important;
        color: white !important;
        border: none !important;
        border-radius: 4px !important;
        padding: 0.5rem 1rem !important;
        font-weight: 500 !important;
        transition: background-color 0.3s ease;
    }
    .stFileUploader > div > div > div > button:hover {
        background-color: #1e40af !important;
    }

    /* Input Box */
    .stChatInputContainer > div {
        background-color: #FFFFFF !important;
        border: 1px solid #CCC !important;
        border-radius: 8px !important;
    }
    .stChatInputContainer textarea {
        color: #333 !important;
    }

    /* Container Styling */
    .app-title {
        text-align: center;
        margin-top: 2rem;
        margin-bottom: 0.5rem;
        font-size: 2.5rem;
        font-weight: 700;
        background: -webkit-linear-gradient(45deg, #60A5FA, #3B82F6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .app-subtitle {
        text-align: center;
        color: #888;
        font-size: 1rem;
        margin-bottom: 3rem;
        font-weight: 300;
    }
</style>
""", unsafe_allow_html=True)

# --- INITIALIZATION ---

# Load Knowledge Base
@st.cache_data
def load_knowledge():
    kb_path = "knowledge.md"
    if os.path.exists(kb_path):
        with open(kb_path, "r", encoding="utf-8") as f:
            return f.read()
    return "Knowledge base not found."

KNOWLEDGE_BASE = load_knowledge()

# Initialize Firebase
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        try:
            # Assuming secrets are properly set in .streamlit/secrets.toml
            creds_dict = dict(st.secrets["firebase"])
            # Format private key properly if it contains escaped newlines
            if 'private_key' in creds_dict:
                creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
            
            cred = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(cred)
            return firestore.client()
        except Exception as e:
            st.warning(f"Firebase initialization skipped or failed. App runs in local mode. Error: {e}")
            return None
    return firestore.client()

db = init_firebase()

# Initialize Gemini
def init_gemini():
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        if api_key != "dummy_api_key_here":
            genai.configure(api_key=api_key)
            return True
    except Exception as e:
        pass
    return False

gemini_ready = init_gemini()

# Initialize Session State
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "こんにちは、Furu_Kanです。Levi's 501の年代判定を行います。まずは**内タグ（ケアラベル）**または**トップボタン裏**の写真をアップロードしてください。"}
    ]

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0


# --- HELPER FUNCTIONS ---

def save_to_firestore(role, text, image_name=None):
    if db:
        try:
            db.collection("sessions").document(st.session_state.session_id).collection("messages").add({
                "role": role,
                "text": text,
                "image_name": image_name,
                "timestamp": datetime.datetime.now()
            })
        except Exception as e:
            pass # Silently fail if Firestore is not connected

def save_appraisal_to_firestore(appraisal_data):
    if db:
        try:
            appraisal_data["session_id"] = st.session_state.session_id
            appraisal_data["timestamp"] = datetime.datetime.now()
            db.collection("appraisals").add(appraisal_data)
        except Exception as e:
            pass # Silently fail if Firestore is not connected

def get_gemini_response(prompt, image=None):
    if not gemini_ready:
        return "Gemini APIキーが設定されていません。`.streamlit/secrets.toml`を確認してください。"
    
    try:
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        
        system_prompt = f"""
        あなたはヴィンテージLevi'sの画像判定AIです。
        ユーザーから提供された画像と、以下の知識ベースを元に読み取れる情報を端的に出力してください。

        【知識ベース】
        {KNOWLEDGE_BASE}

        【出力フォーマットの厳格なルール】
        1. 挨拶や感情的な表現（！や絵文字など）は一切不要です。
        2. 太字やMarkdownの文字修飾（*や**、<b>タグなど）は一切使用しないでください。すべてプレーンテキストで出力してください。
        3. 以下の形式に則り、必要な情報のみを箇条書き（「項目：結果」の形式）で出力してください。
        4. 各項目の間には必ず改行を入れ、見やすく縦に並べてください（1行にまとめて記述するのは禁止です）。

        （出力例・未確定の場合）
        読み取れた特徴：[ここに画像から分かった特徴を記載]

        年代の可能性：[ここに可能性のある年代を記載]

        次のステップ：[次に必要な画像の部位を指定]

        （出力例・確定した場合）
        読み取れた特徴：[ここに画像から分かった特徴を記載]

        確定した年代：[推定年代]

        モデル名：[モデル名]

        価値の目安：[相場]
        
        【指示】
        1枚で年代が確定できない場合は、「次のステップ：」にて追加の画像を要求してください。
        年代が完全に特定できた場合は、ユーザーへの返信テキストの【最後に】必ず以下のJSONフォーマットを改行して出力してください。このJSON自体には文字修飾などは付けず、そのまま出力してください。
        
        {{"is_final": true, "era": "年代", "model": "モデル名", "value": "価値の目安", "trivia": "ウンチク"}}
        
        年代が未確定で追加画像が必要な場合は JSON は出力しないでください。
        """
        
        contents = [system_prompt]
        
        # Append history (limited to avoid huge context)
        for msg in st.session_state.messages[-4:]:
            if msg["role"] == "user":
                contents.append(f"User: {msg['content']}")
            else:
                contents.append(f"Expert: {msg['content']}")
        
        contents.append(f"User: {prompt}")
        if image:
            contents.append(image)
            
        response = model.generate_content(contents)
        response_text = response.text
        
        # Parse JSON if final appraisal
        import json
        import re
        
        json_match = re.search(r'(\{.*"is_final":\s*true.*\})', response_text, re.DOTALL)
        if json_match:
            try:
                appraisal_data = json.loads(json_match.group(1))
                save_appraisal_to_firestore(appraisal_data)
                
                # Cleanup text for display (remove json)
                display_text = response_text.replace(json_match.group(1), "").strip()
                return display_text
            except json.JSONDecodeError:
                pass # Fallback to normal display if parsing fails
                
        return response_text
    except Exception as e:
        return f"鑑定中にエラーが発生しました: {e}"

# --- UI LAYOUT ---

st.markdown('<div class="app-title">Furu_Kan</div>', unsafe_allow_html=True)
st.markdown('<div class="app-subtitle">Vintage Levi\'s 501 Intelligent Appraiser</div>', unsafe_allow_html=True)

# Display Chat Messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "image" in msg and msg["image"] is not None:
            st.image(msg["image"], width=300)

# Input Area
user_text = st.chat_input("メッセージを入力...")
uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "jpeg", "png"], key=f"uploader_{st.session_state.uploader_key}", label_visibility="collapsed")

if user_text or uploaded_file:
    # Process User Input
    user_img = None
    display_img = None
    
    if uploaded_file:
        user_img = Image.open(uploaded_file)
        # Create a display copy to avoid showing closed file errors later
        display_img = user_img.copy() 
    
    prompt = user_text if user_text else "画像をアップロードしました。鑑定をお願いします。"
    
    # Add User Message to UI
    st.session_state.messages.append({"role": "user", "content": prompt, "image": display_img})
    with st.chat_message("user"):
        st.write(prompt)
        if display_img:
            st.image(display_img, width=300)
    
    # Save to Firestore
    save_to_firestore("user", prompt, uploaded_file.name if uploaded_file else None)

    # Get Assistant Response
    with st.chat_message("assistant"):
        with st.spinner("鑑定中..."):
            response_text = get_gemini_response(prompt, user_img)
            st.write(response_text)
            
    # Add Assistant Message to UI
    st.session_state.messages.append({"role": "assistant", "content": response_text})
    save_to_firestore("assistant", response_text)

    # Clear uploader by rerunning
    st.session_state.uploader_key += 1
    st.rerun()

