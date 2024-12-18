from flask import Flask, render_template, jsonify, request
from bs4 import BeautifulSoup
from openai import OpenAI
import os
from dotenv import load_dotenv
from playwright.async_api import async_playwright
import asyncio
from functools import wraps
from asgiref.sync import async_to_sync
import json
import httpx

load_dotenv()

app = Flask(__name__)
client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    http_client=httpx.Client()
)

# Cache for article summaries
article_summaries = {}

def async_route(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return async_to_sync(f)(*args, **kwargs)
    return wrapper

async def get_article_content(page, url):
    """Extract article content using Playwright"""
    try:
        print(f"Navigating to article: {url}")
        await page.goto(url)
        
        # Wait for article content to load
        article = await page.wait_for_selector('article')
        if article:
            content = await article.inner_text()
            print(f"Found article content: {len(content)} characters")
            return content
        print("No article element found")
        return "Error: Could not find article content"
    except Exception as e:
        print(f"Error fetching article content: {str(e)}")
        return f"Error: {str(e)}"

async def login_if_needed(page):
    """Check if login is needed and perform login if necessary"""
    try:
        # Check if we're already logged in by looking for the Dashboard button
        dashboard = await page.query_selector('button:has-text("Dashboard")')
        if dashboard:
            print("Already logged in")
            return

        print("Navigating to Substack login page...")
        await page.goto('https://substack.com/sign-in')
        
        # Get credentials from env
        email = os.getenv('SUBSTACK_EMAIL')
        password = os.getenv('SUBSTACK_PASSWORD')
        
        if not email or not password:
            print("No credentials found in .env file. Please add SUBSTACK_EMAIL and SUBSTACK_PASSWORD")
            print("Waiting for manual login...")
            print("You have 60 seconds to complete the login.")
            
            try:
                await page.wait_for_selector('button:has-text("Dashboard")', timeout=60000)
                print("Login successful!")
            except Exception as e:
                print("Login wait timed out or failed:", str(e))
                await page.screenshot(path='login_timeout.png')
                raise Exception("Login failed")
        else:
            print("Attempting automatic login...")
            try:
                # Wait for and fill email field
                await page.wait_for_selector('input[type="email"]')
                await page.fill('input[type="email"]', email)
                
                # Click the "Sign in with password" link
                login_option = await page.wait_for_selector('.login-option')
                await login_option.click()
                
                # Wait for and fill password field
                await page.wait_for_selector('input[type="password"]')
                await page.fill('input[type="password"]', password)
                
                # Click sign in button
                sign_in_button = await page.wait_for_selector('button:has-text("Continue")')
                await sign_in_button.click()
                
                # Wait for successful login
                print("Waiting for login completion...")
                await page.wait_for_selector('button:has-text("Dashboard")', timeout=10000)
                print("Automatic login successful!")
                
            except Exception as e:
                print(f"Automatic login failed: {str(e)}")
                print("Falling back to manual login...")
                print("Please log in manually. You have 60 seconds.")
                
                try:
                    await page.wait_for_selector('button:has-text("Dashboard")', timeout=60000)
                    print("Manual login successful!")
                except Exception as e:
                    print("Login wait timed out or failed:", str(e))
                    await page.screenshot(path='login_timeout.png')
                    raise Exception("Login failed")
    
    except Exception as e:
        print(f"Error in login_if_needed: {str(e)}")
        raise e

def generate_summary(content):
    """Generate a summary using OpenAI's API"""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates concise summaries of articles."},
                {"role": "user", "content": f"Please provide a 2-3 sentence summary of this article:\n\n{content}"}
            ],
            max_tokens=150
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error generating summary: {str(e)}")
        return f"Error generating summary: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/refresh')
@async_route
async def refresh():
    """Fetch article metadata from Substack inbox"""
    try:
        async with async_playwright() as p:
            print("Launching browser...")
            browser = await p.chromium.launch(
                headless=False,  # Set to False to see what's happening
                slow_mo=50  # Slow down operations to see what's happening
            )
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # First check login
                await login_if_needed(page)
                
                print("Navigating to inbox...")
                await page.goto('https://substack.com/inbox')
                await asyncio.sleep(2)  # Give the page a moment to load
                
                print("Looking for article links...")
                # Try different selectors in order of specificity
                selectors_to_try = [
                    'a[href*="/p/"]',  # Standard article links
                    '.post-preview a',  # Post preview links
                    'article a',        # Any link within article tags
                    '.post-title a',    # Post title links
                    '.post a',          # Any link within post class
                    'a[href*="substack.com"]'  # Any Substack link
                ]
                
                # First collect all article information before processing
                article_infos = []
                for selector in selectors_to_try:
                    print(f"Trying selector: {selector}")
                    links = await page.query_selector_all(selector)
                    print(f"Found {len(links)} links with {selector}")
                    if links:
                        # Collect all article info first
                        for link in links[:3]:  # Only process top 3 for now
                            try:
                                url = await link.get_attribute('href')
                                
                                # Look for thumbnails and metadata in the article preview container
                                try:
                                    # Find thumbnails, title and metadata
                                    container_info = await page.evaluate('''(link) => {
                                        const container = link.closest('.reader2-post-container');
                                        if (!container) return null;
                                        
                                        // Get blog name and thumbnail
                                        const pubElement = container.querySelector('.pub-name a');
                                        const blogName = pubElement ? pubElement.innerText.trim() : null;
                                        
                                        const blogThumbContainer = container.querySelector('.reader2-post-head img');
                                        const blogThumbnail = blogThumbContainer ? blogThumbContainer.src : null;
                                        
                                        // Get article title and thumbnail
                                        const titleElement = container.querySelector('.reader2-post-title');
                                        const title = titleElement ? titleElement.innerText.trim() : null;
                                        
                                        // Get subtitle
                                        const subtitleElement = container.querySelector('.reader2-secondary');
                                        const subtitle = subtitleElement ? subtitleElement.innerText.trim() : null;
                                        
                                        const articleThumbContainer = container.querySelector('.reader2-post-picture-container img');
                                        const articleThumbnail = articleThumbContainer ? articleThumbContainer.src : null;
                                        
                                        // Get date
                                        const dateElement = container.querySelector('.inbox-item-timestamp');
                                        const date = dateElement ? dateElement.innerText.trim() : null;
                                        
                                        // Get metaText (author and duration)
                                        const metaElement = container.querySelector('.reader2-item-meta');
                                        const metaText = metaElement ? metaElement.innerText.trim() : 'Unknown Author / Duration';
                                        
                                        return { 
                                            blogName, 
                                            blogThumbnail,
                                            title,
                                            subtitle,
                                            articleThumbnail,
                                            date,
                                            metaText
                                        };
                                    }''', link)
                                    
                                    if container_info and container_info['title']:
                                        article_infos.append({
                                            'url': url,
                                            'title': container_info['title'],
                                            'subtitle': container_info['subtitle'],
                                            'article_thumbnail': container_info['articleThumbnail'],
                                            'blog_thumbnail': container_info['blogThumbnail'],
                                            'blog_name': container_info['blogName'] or 'Unknown Blog',
                                            'date': container_info['date'],
                                            'metaText': container_info['metaText']
                                        })
                                        print(f"Found article: {container_info['title']}")
                                
                                except Exception as e:
                                    print(f"Error finding article info: {str(e)}")
                                    continue
                                
                            except Exception as e:
                                print(f"Error collecting article info: {str(e)}")
                                continue
                        
                        if article_infos:
                            break  # Use the first successful selector that found articles
                
                print(f"Found {len(article_infos)} articles")
                
                # If no articles found, take a screenshot for debugging
                if len(article_infos) == 0:
                    print("No articles found, taking screenshot...")
                    await page.screenshot(path='debug_screenshot.png')
                    print("Screenshot saved as debug_screenshot.png")
                    await asyncio.sleep(60)  # Keep browser open for debugging
                
                return jsonify({
                    'articles': article_infos
                })

            except Exception as e:
                print(f"Error in refresh: {str(e)}")
                await page.screenshot(path='error_screenshot.png')
                print("Error screenshot saved as error_screenshot.png")
                raise e
            finally:
                await asyncio.sleep(2)  # Give time to see what happened
                await browser.close()

    except Exception as e:
        print(f"Error in refresh: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/summarize', methods=['POST'])
@async_route
async def summarize():
    """Generate summary for a single article"""
    try:
        data = request.json
        article = data['article']
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                content = await get_article_content(page, article['url'])
                if not content.startswith("Error"):
                    summary = generate_summary(content)
                    if summary:
                        return jsonify({'summary': summary})
                    else:
                        return jsonify({'error': 'Failed to generate summary'}), 500
                else:
                    return jsonify({'error': 'Failed to get content'}), 500

            finally:
                await browser.close()

    except Exception as e:
        print(f"Error in summarize: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)
