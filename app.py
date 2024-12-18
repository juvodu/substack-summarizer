from flask import Flask, render_template, jsonify
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

async def get_inbox_articles():
    """Fetch articles from Substack inbox using Playwright"""
    articles = []
    
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch(
            headless=False,  # Set to False to see what's happening
            slow_mo=50  # Slow down operations to see what's happening
        )
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
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
                    return []
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
                    
                   # TODO: Handle 2FA via email

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
                        return []
            
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
                    for link in links[:3]:  # Only process top 3
                        try:
                            url = await link.get_attribute('href')
                            title = await link.inner_text()
                            
                            # Try to find the thumbnail image
                            thumbnail_url = None
                            
                            # Look for image in the article preview container
                            try:
                                # Find the thumbnail container and get the image src
                                img_element = await page.evaluate('''(link) => {
                                    // Find the closest article container
                                    const articleContainer = link.closest('.reader2-post-container');
                                    if (!articleContainer) return null;
                                    
                                    // Find the thumbnail container
                                    const thumbnailContainer = articleContainer.querySelector('.reader2-post-picture-container');
                                    if (!thumbnailContainer) return null;
                                    
                                    // Get the image source
                                    const img = thumbnailContainer.querySelector('img');
                                    return img ? img.src : null;
                                }''', link)
                                
                                if img_element:
                                    thumbnail_url = img_element
                                    print(f"Found thumbnail: {thumbnail_url}")
                            except Exception as e:
                                print(f"Error finding thumbnail: {str(e)}")
                            
                            if url and title:
                                article_infos.append({
                                    'url': url,
                                    'title': title.strip(),
                                    'thumbnail': thumbnail_url
                                })
                        except Exception as e:
                            print(f"Error collecting article info: {str(e)}")
                    break  # Use the first successful selector
            
            print(f"Collected info for {len(article_infos)} articles")
            
            # Now process each article
            for article_info in article_infos:
                url = article_info['url']
                title = article_info['title']
                print(f"\nProcessing article: {title}")
                
                # Generate unique ID for the article
                article_id = url
                
                if article_id not in article_summaries:
                    content = await get_article_content(page, url)
                    if not content.startswith("Error"):
                        summary = generate_summary(content)
                        if not summary.startswith("Error"):
                            article_summaries[article_id] = {
                                'title': title,
                                'summary': summary,
                                'link': url,
                                'thumbnail': article_info.get('thumbnail'),
                                'date': 'Recent'
                            }
                            print(f"Generated new summary for: {title}")
                        else:
                            print(f"Error generating summary: {summary}")
                    else:
                        print(f"Error getting content: {content}")
                else:
                    print(f"Using cached summary for: {title}")
                
                if article_id in article_summaries:
                    articles.append(article_summaries[article_id])
            
            print(f"\nReturning {len(articles)} articles")
            
            # If no articles found, take a screenshot for debugging
            if len(articles) == 0:
                print("No articles found, taking screenshot...")
                await page.screenshot(path='debug_screenshot.png')
                print("Screenshot saved as debug_screenshot.png")
            
            # Wait for user input before closing
            if len(articles) == 0:
                print("\nKeeping browser open for 60 seconds...")
                await asyncio.sleep(60)  # Keep browser open for 60 seconds
            
        except Exception as e:
            print(f"Error fetching inbox: {str(e)}")
            # Take a screenshot on error
            await page.screenshot(path='error_screenshot.png')
            print("Error screenshot saved as error_screenshot.png")
            await asyncio.sleep(5)  # Keep browser open briefly on error
        finally:
            await asyncio.sleep(2)  # Give time to see what happened
            await context.close()
            await browser.close()
    
    return articles

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/refresh')
@async_route
async def refresh():
    articles = await get_inbox_articles()
    return jsonify(articles)

if __name__ == '__main__':
    app.run(debug=True, port=5001)
