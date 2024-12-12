from flask import Flask, render_template, jsonify, request
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

app = Flask(__name__)
client = OpenAI()  # It will automatically use OPENAI_API_KEY from environment

# Temporary storage for articles and summaries
# In a production app, you'd want to use a proper database
articles = {}

def generate_summary(content):
    """Generate a summary using OpenAI's API"""
    try:
        print(f"Generating summary for content of length: {len(content)}")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates concise summaries of articles."},
                {"role": "user", "content": f"Please provide a concise summary of this article: {content}"}
            ],
            max_tokens=150
        )
        summary = response.choices[0].message.content
        print(f"Generated summary: {summary}")
        return summary
    except Exception as e:
        print(f"Error in generate_summary: {str(e)}")
        return f"Error generating summary: {str(e)}"

def extract_article_content(url):
    """Extract article content from Substack URL"""
    try:
        print(f"Fetching article from: {url}")
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the main article content
        article_content = []
        
        # Get the title
        title = soup.find('h1', class_='post-title')
        if title:
            print(f"Found title: {title.get_text().strip()}")
            article_content.append(title.get_text().strip())
        else:
            print("No title found")
        
        # Get the main content
        content_div = soup.find('div', class_='body markup')
        if content_div:
            print("Found main content div")
            paragraphs = content_div.find_all(['p', 'h2', 'h3', 'blockquote'])
            for p in paragraphs:
                article_content.append(p.get_text().strip())
            print(f"Extracted {len(paragraphs)} paragraphs")
        else:
            print("No main content div found")
        
        content = "\n\n".join(article_content)
        print(f"Total content length: {len(content)} characters")
        return content
    except Exception as e:
        print(f"Error in extract_article_content: {str(e)}")
        return f"Error extracting content: {str(e)}"

@app.route('/')
def home():
    return render_template('index.html', articles=articles)

@app.route('/add_article', methods=['POST'])
def add_article():
    data = request.json
    url = data.get('url')
    title = data.get('title')
    
    if url and title:
        print(f"Processing article: {title} from {url}")
        content = extract_article_content(url)
        if content.startswith("Error"):
            return jsonify({'success': False, 'message': content})
            
        summary = generate_summary(content)
        if summary.startswith("Error"):
            return jsonify({'success': False, 'message': summary})
        
        articles[url] = {
            'title': title,
            'summary': summary,
            'original_url': url
        }
        print(f"Successfully processed article: {title}")
        return jsonify({'success': True, 'message': 'Article added successfully'})
    return jsonify({'success': False, 'message': 'Missing URL or title'})

@app.route('/get_summary/<path:url>')
def get_summary(url):
    article = articles.get(url)
    if article:
        return jsonify(article)
    return jsonify({'error': 'Article not found'}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5001)
