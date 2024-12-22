from flask import Flask, render_template, jsonify, request, session
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
import secrets

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

def get_openai_client():
    """Get OpenAI client from session"""
    api_key = session.get('api_key')
    if not api_key:
        return None
    return OpenAI(api_key=api_key, http_client=httpx.Client())

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated

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

async def login_if_needed(page, email, password):
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
        if not email or not password:
            print("No credentials found in session. Please log in.")
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
                print("Waiting for email field...")
                await page.wait_for_selector('input[type="email"]')
                print("Found email field, filling...")
                await page.fill('input[type="email"]', email)
                
                # Click the "Sign in with password" link
                print("Looking for password login option...")
                login_option = await page.wait_for_selector('.login-option')
                print("Found login option, clicking...")
                await login_option.click()
                await page.wait_for_timeout(1000)  # Wait a bit after clicking
                
                # Wait for and fill password field
                print("Waiting for password field...")
                await page.wait_for_selector('input[type="password"]')
                print("Found password field, filling...")
                await page.fill('input[type="password"]', password)
                await page.wait_for_timeout(1000)  # Wait a bit after filling
                
                # Click sign in button
                print("Looking for continue button...")
                sign_in_button = await page.wait_for_selector('button:has-text("Continue")')
                print("Found continue button, clicking...")
                await sign_in_button.click()
                await page.wait_for_timeout(2000)  # Wait longer after clicking login
                
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

def estimate_tokens(text):
    """Estimate the number of tokens in a text string.
    This is a simple estimation - actual token count may vary."""
    # GPT models typically use ~4 characters per token on average
    return len(text) // 4

def truncate_to_token_limit(text, max_tokens=16000):
    """Truncate text to stay within token limit, leaving room for system message and instructions"""
    estimated_tokens = estimate_tokens(text)
    
    if estimated_tokens <= max_tokens:
        return text
        
    # If text is too long, truncate it proportionally
    # We use characters as a proxy since we can't count tokens exactly
    max_chars = (max_tokens * 4)  # Convert tokens to approximate char count
    return text[:max_chars]

def generate_summary(content, length=2):  
    """Generate a summary using OpenAI's API"""
    try:
        client = get_openai_client()
        if not client:
            return "Error: OpenAI client not initialized"
        
        # Define summary length parameters
        length_settings = {
            1: {"sentences": "1-2", "tokens": 100},  
            2: {"sentences": "3-4", "tokens": 150},  
            3: {"sentences": "5-6", "tokens": 200}   
        }
        
        setting = length_settings.get(int(length), length_settings[2])
        
        # Truncate content to fit within token limit
        truncated_content = truncate_to_token_limit(content)
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates concise summaries of articles."},
                {"role": "user", "content": f"Please provide a {setting['sentences']} sentence summary of this article:\n\n{truncated_content}"}
            ],
            max_tokens=setting['tokens']
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error generating summary: {str(e)}")
        return f"Error generating summary: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/save_credentials', methods=['POST'])
def save_credentials():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        api_key = data.get('apiKey')

        if not all([email, password, api_key]):
            return jsonify({'error': 'Missing credentials'}), 400

        # Initialize OpenAI client to validate API key
        try:
            test_client = OpenAI(api_key=api_key, http_client=httpx.Client())
            # Test the API key with a minimal request
            test_client.models.list()
        except Exception as e:
            return jsonify({'error': 'Invalid OpenAI API key'}), 401

        # Store credentials in session
        session['authenticated'] = True
        session['email'] = email
        session['password'] = password
        session['api_key'] = api_key

        return jsonify({'message': 'Saved credentials successfully'})

    except Exception as e:
        print(f"Failed to save credentials: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear_credentials', methods=['POST'])
def clear_credentials():
    session.clear()
    return jsonify({'message': 'Cleared credentials successfully'})

@app.route('/api/check_credentials', methods=['GET'])
def check_credentials():
    return jsonify({
        'authenticated': session.get('authenticated', False)
    })

@app.route('/fetch_articles')
@require_auth
@async_route
async def fetch_articles():
    """Fetch article metadata from Substack inbox"""
    try:
        article_limit = int(request.args.get('limit', 5))
        
        async with async_playwright() as p:
            print("Launching browser...")
            browser = await p.chromium.launch(
                headless=True,
                slow_mo=50
            )
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 720}
            )
            page = await context.new_page()

            try:
                # Use credentials from session
                email = session.get('email')
                password = session.get('password')
                
                if not email or not password:
                    return jsonify({'error': 'Session expired'}), 401

                # First check login
                await login_if_needed(page, email, password)
                
                print("Navigating to inbox...")
                await page.goto('https://substack.com/inbox')
                await asyncio.sleep(2)  
                
                print("Looking for article links...")
                # Try different selectors in order of specificity
                selectors_to_try = [
                    'a[href*="/p/"]',  
                    '.post-preview a',  
                    'article a',        
                    '.post-title a',    
                    '.post a',          
                    'a[href*="substack.com"]'  
                ]
                
                # First collect all article information before processing
                article_infos = []
                for selector in selectors_to_try:
                    print(f"Trying selector: {selector}")
                    links = await page.query_selector_all(selector)
                    print(f"Found {len(links)} links with {selector}")
                    if links:
                        # Collect all article info first
                        for link in links[:article_limit]:  
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
                            break  
                
                print(f"Found {len(article_infos)} articles")
                
                # If no articles found, take a screenshot for debugging
                if len(article_infos) == 0:
                    print("No articles found, taking screenshot...")
                    await page.screenshot(path='debug_screenshot.png')
                    print("Screenshot saved as debug_screenshot.png")
                    await asyncio.sleep(60)  
                
                return jsonify({
                    'articles': article_infos
                })

            except Exception as e:
                print(f"Error in refresh: {str(e)}")
                await page.screenshot(path='error_screenshot.png')
                print("Error screenshot saved as error_screenshot.png")
                raise e
            finally:
                await asyncio.sleep(2)  
                await browser.close()

    except Exception as e:
        print(f"Error in refresh: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/generate_summary', methods=['POST'])
@require_auth
@async_route
async def generate_summary_endpoint():
    """Generate summary for a single article"""
    try:
        data = request.get_json()
        url = data.get('url')
        length = data.get('length', '2')
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                slow_mo=50
            )
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 720}
            )
            page = await context.new_page()

            try:
                content = await get_article_content(page, url)
                if not content.startswith("Error"):
                    summary = generate_summary(content, length)
                    if summary:
                        return jsonify({'summary': summary})
                    else:
                        return jsonify({'error': 'Failed to generate summary'}), 500
                else:
                    return jsonify({'error': content}), 500

            finally:
                await browser.close()

    except Exception as e:
        print(f"Error in generate_summary: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)
