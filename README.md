Installation (Local)
Clone the repository:
git clone https://github.com/vi3hnu17/Ecoach.git
cd Ecoach
Install dependencies:
pip install -r requirements.txt
Set your API key:
Option A: Environment variable
export GEMINI_API_KEY="your_api_key_here"
Option B: Streamlit secrets
Create:
.streamlit/secrets.toml
Add:
GEMINI_API_KEY = "your_api_key_here"
Run the app:
streamlit run Streamlit_chatbot.py
