# 🚀 Universal Low Latency Runbook

This project helps developers **analyze code snippets** for potential **latency bottlenecks** using:
- A rule-based **static analyzer**
- An optional LLM-powered **GPT reviewer** via **OpenRouter.ai**

Built with ❤️ by [Gauri Bhardwaj](https://github.com/gauribhardwaj)

---

## 📸 Demo
![screenshot](https://github.com/gauribhardwaj/Low-Latency-101/assets/demo.png)

---

## 📂 Project Structure

```
Low-Latency-101/
│
├── app.py                            # 🔵 Main Streamlit UI
├── .env                              # 🔐 Your API key (not checked in)
├── latency_engine/
│   ├── __init__.py
│   ├── gpt_review.py                 # 🤖 GPT LLM handler
│   └── latency_analyzer.py          # 🧠 Rule-based static analysis engine
│
├── latency_engine/rules/
│   ├── python_rules.json
│   ├── java_rules.json
│   └── cpp_rules.json               # 🔍 Language-specific rules
│
├── requirements.txt                 # 📦 Python dependencies
└── README.md                        # 📘 You're here!
```

---

## 💻 Run Locally

### ✅ 1. Clone the repo

```bash
git clone https://github.com/gauribhardwaj/Low-Latency-101.git
cd Low-Latency-101
```

### ✅ 2. Create a virtual environment (optional but recommended)

```bash
python -m venv venv
source venv/bin/activate       # On Mac/Linux
venv\Scripts\activate        # On Windows
```

### ✅ 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### ✅ 4. Get OpenRouter API Key

1. Go to [https://openrouter.ai](https://openrouter.ai)
2. Login → Get your **API key** (starts with `sk-or-...`)
3. Copy it.

Create a `.env` file in the project root:

```env
OPENROUTER_API_KEY=sk-or-your-api-key-here
```

> ⚠️ This file should **not be committed**. It's already added in `.gitignore`.

### ✅ 5. Run the app

```bash
streamlit run app.py
```

### ✅ 6. Use the UI

1. Select the language: `Python`, `Java`, or `C++`
2. Paste your code snippet
3. Click **"Analyze Code"** to run the static engine
4. (Optional) Tick ✅ the **GPT Review** checkbox to get suggestions from DeepSeek (via OpenRouter)

---

## 🧠 Sample Code (Python)

```python
for i in range(10000):
    print("Iteration", i)
    result = [x * x for x in range(1000)]
```

**Static Output**:
- ❌ I/O in hot loop
- ❌ List allocations per iteration
- Score: 70/100

**GPT Output** (DeepSeek):
- Use generator expressions
- Cache function calls
- Buffer print statements

---

## 🧰 Dependencies

- `streamlit`
- `requests`
- `dotenv`
- `re`, `json`, `os`, `logging`

Install via:

```bash
pip install -r requirements.txt
```

---

## 📡 Optional: Deploy to Streamlit Cloud

1. Push this repo to GitHub
2. Go to [streamlit.io/cloud](https://streamlit.io/cloud) and deploy it
3. Add your `OPENROUTER_API_KEY` as a **secret**

---

## 📬 Contact

For feedback or collaborations, reach out on [LinkedIn](https://www.linkedin.com/in/gauribhardwaj7) or file an issue.

---

## 🛡️ License

MIT License © [gauribhardwaj](https://github.com/gauribhardwaj)
