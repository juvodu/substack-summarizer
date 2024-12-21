// Cache management
const CACHE_KEY_ARTICLES = 'substack_articles';
const CACHE_KEY_SUMMARIES = 'substack_summaries';
const CACHE_EXPIRY_HOURS = 24; // Cache expires after 24 hours
const SETTINGS_KEY = 'substack_settings';

let currentSummaryLength = '2'; // Default to moderate

function saveToCache(key, data) {
    try {
        localStorage.setItem(key, JSON.stringify({
            timestamp: new Date().getTime(),
            data: data,
            order: Object.keys(data) // Save the order of articles
        }));
    } catch (e) {
        console.error('Error saving to cache:', e);
    }
}

function getFromCache(key) {
    try {
        const cacheData = localStorage.getItem(key);
        if (!cacheData) {
            return null;
        }

        const parsed = JSON.parse(cacheData);
        const now = new Date().getTime();
        
        // Cache valid for 24 hours
        if (now - parsed.timestamp > 24 * 60 * 60 * 1000) {
            localStorage.removeItem(key);
            return null;
        }

        return parsed;
    } catch (e) {
        console.error('Error reading from cache:', e);
        return null;
    }
}

function getCachedArticles() {
    const cachedData = getFromCache(CACHE_KEY_ARTICLES);
    return cachedData ? cachedData.data : {};
}

function getCachedSummaries() {
    const cachedData = getFromCache(CACHE_KEY_SUMMARIES);
    return cachedData ? cachedData.data : {};
}

function createArticleCard(article, index) {
    const cachedSummaries = getCachedSummaries();
    const hasCachedSummary = cachedSummaries && cachedSummaries[article.url];
    
    const summaryHtml = hasCachedSummary ? `
        <div class="ai-badge">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            AI Summary
        </div>
        <p class="article-summary">${cachedSummaries[article.url]}</p>
    ` : `
        <div class="summary-placeholder">
            <div class="spinner"></div>
            <div>Generating AI summary...</div>
        </div>
    `;

    return `
        <div class="article" id="article-${index}" data-url="${article.url}">
            <div class="article-header">
                <div class="blog-info">
                    ${article.blog_thumbnail ? 
                        `<img class="blog-thumbnail" src="${article.blog_thumbnail}" alt="Blog thumbnail">` : 
                        '<div class="blog-thumbnail placeholder-thumbnail"></div>'
                    }
                    <span class="blog-name">${article.blog_name}</span>
                </div>
                <span class="article-date">${article.date}</span>
            </div>
            <div class="article-main">
                <div class="article-content">
                    <h2 class="article-title">${article.title}</h2>
                    ${article.subtitle ? `<div class="article-subtitle">${article.subtitle}</div>` : ''}
                    <div class="article-summary-container">
                        ${summaryHtml}
                    </div>
                    <div class="article-meta">
                        ${article.metaText}
                    </div>
                    <a href="${article.url}" class="article-link" target="_blank">Full Article →</a>
                </div>
                ${article.article_thumbnail ? 
                    `<img class="article-thumbnail" src="${article.article_thumbnail}" alt="Article thumbnail">` : 
                    '<div class="article-thumbnail placeholder-thumbnail"></div>'
                }
            </div>
        </div>
    `;
}

async function displayCachedArticles() {
    const cachedData = getFromCache(CACHE_KEY_ARTICLES);
    const cachedSummaries = getCachedSummaries();
    
    if (cachedData && cachedData.data && Object.keys(cachedData.data).length > 0) {
        const articleLimit = parseInt($('#article-limit').val());
        
        // Use the saved order to display articles
        const articleOrder = cachedData.order || Object.keys(cachedData.data);
        const articles = articleOrder
            .map(url => cachedData.data[url])
            .slice(0, articleLimit);

        articles.forEach((article, index) => {
            const articleElement = $(createArticleCard(article, index));
            $('#articles-container').append(articleElement);
            
            // If we have a cached summary, update the UI immediately
            if (cachedSummaries && cachedSummaries[article.url]) {
                articleElement.find('.article-summary-container').html(`
                    <div class="ai-badge">
                        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        AI Summary
                    </div>
                    <p class="article-summary">${cachedSummaries[article.url]}</p>
                `);
            }
        });
    }
}

function loadSettings() {
    try {
        const settings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
        if (settings.summaryLength) {
            currentSummaryLength = settings.summaryLength;
            $(`input[name="summary-length"][value="${currentSummaryLength}"]`).prop('checked', true);
        }
        if (settings.articleLimit) {
            $('#article-limit').val(settings.articleLimit);
            $('#article-limit-value').text(settings.articleLimit);
        }
    } catch (e) {
        console.error('Error loading settings:', e);
    }
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function retryRequest(fn, retries = 3, delayMs = 1000) {
    for (let i = 0; i < retries; i++) {
        try {
            return await fn();
        } catch (error) {
            if (i === retries - 1) throw error;
            await delay(delayMs);
        }
    }
}

async function generateSummary(article, articleElement) {
    try {
        const summaryLength = $('input[name="summary-length"]:checked').val();
        
        const response = await retryRequest(() =>
            fetch('/generate_summary', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url: article.url,
                    length: parseInt(summaryLength)
                })
            })
        );

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        
        if (result.error) {
            throw new Error(result.error);
        }

        // Update the summary in the article card
        articleElement.find('.article-summary-container').html(`
            <div class="ai-badge">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                AI Summary
            </div>
            <p class="article-summary">${result.summary}</p>
        `);

        // Cache the summary
        const cachedSummaries = getCachedSummaries() || {};
        cachedSummaries[article.url] = result.summary;
        saveToCache(CACHE_KEY_SUMMARIES, cachedSummaries);

    } catch (error) {
        console.error('Error generating summary:', error);
        articleElement.find('.article-summary-container').html(`
            <div class="error-message">
                Failed to generate summary. Please try again later.<br>
                Error: ${error.message}
            </div>
        `);
    }
}

async function refreshArticles() {
    // Don't clear existing articles yet
    $('#loading').show();
    $('#progress-container').show();

    try {
        const articleLimit = parseInt($('#article-limit').val());
        
        // Save settings
        localStorage.setItem(SETTINGS_KEY, JSON.stringify({
            summaryLength: $('input[name="summary-length"]:checked').val(),
            articleLimit: articleLimit
        }));

        const response = await fetch(`/fetch_articles?limit=${articleLimit}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        if (!result.articles) {
            throw new Error('No articles found in response');
        }
        
        // Cache the articles
        const articlesMap = {};
        result.articles.forEach(article => {
            articlesMap[article.url] = article;
        });
        saveToCache(CACHE_KEY_ARTICLES, articlesMap);

        // Only clear the container right before displaying new articles
        $('#articles-container').empty();
        
        // Display articles and generate summaries
        result.articles.forEach((article, index) => {
            const articleElement = $(createArticleCard(article, index));
            $('#articles-container').append(articleElement);
            generateSummary(article, articleElement);
        });

    } catch (error) {
        console.error('Error fetching articles:', error);
        // Don't clear existing articles on error
        const errorElement = $(`
            <div class="error-message" style="margin: 20px 0;">
                Failed to fetch articles. Please try again later.<br>
                Error: ${error.message}
            </div>
        `);
        // Insert error message at the top without removing existing articles
        $('#articles-container').prepend(errorElement);
    } finally {
        $('#loading').hide();
        $('#progress-container').hide();
    }
}

// Document ready handler
$(document).ready(function() {
    // Load saved settings
    loadSettings();
    // Display cached articles on page load
    displayCachedArticles();
    
    // Event handlers
    $('#refresh-button').click(refreshArticles);
    
    // Update article limit display when slider moves
    $('#article-limit').on('input', function() {
        const newLimit = parseInt($(this).val());
        $('#article-limit-value').text(newLimit);
    });
});
