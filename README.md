# Substack AI Summarizer

A web app that helps you manage your Substack reading list by providing AI-generated summaries of articles from authors you subscribe to. The app uses web crawling to fetch artcles from your Substack inbox https://substack.com/inbox and uses OpenAI's GPT-3 API to generate summaries. This way you can get a quick overview of what's new on your Substack inbox and dive deeper into the most important artcles only. If you are like me and have a huge Substack inbox, this app is a great time saver.

## Features

- View your Substack Inbox with AI generated summaries
- Dive into the original, full article with the provided link as needed

## Setup

1. Create a `.env` file in the root directory with your OpenAI API key and Substack login credentials:
```
OPENAI_API_KEY=your_key_here
SUBSTACK_EMAIL=your_substack_email_here
SUBSTACK_PASSWORD=your_substack_password_here
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python3 app.py
```

## Constraints
At thos point (December 2024) Substack does not expose a public API. Substack exposes a RSS /feed endpoint for each blog. However there is no RSS feed for the inbox, which is the use case this app covers. 

## Respect the Authors
- For private use only (not for commercial use)
- Data sent to OpenAI's API is not used for model training as stated in the [privacy policy](https://platform.openai.com/docs/concepts/privacy).