// Cache management
const CACHE_KEY_ARTICLES = 'substack_articles';
const CACHE_KEY_SUMMARIES = 'substack_summaries';
const CACHE_EXPIRY_HOURS = 24; // Cache expires after 24 hours
const SETTINGS_KEY = 'substack_settings';

let currentSummaryLength = '2'; // Default to moderate

// Authentication state
let isAuthenticated = false;

// Update access section UI based on authentication state
function updateAccessSectionUI(authenticated) {
    const accessSection = document.getElementById('access-section');
    if (authenticated) {
        accessSection.classList.add('authenticated');
        accessSection.removeAttribute('open');
    } else {
        accessSection.classList.remove('authenticated');
        accessSection.setAttribute('open', '');
    }
}

// Check authentication status
async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/status');
        const data = await response.json();
        isAuthenticated = data.authenticated;
        updateAccessSectionUI(isAuthenticated);
        return isAuthenticated;
    } catch (e) {
        console.error('Error checking auth status:', e);
        updateAccessSectionUI(false);
        return false;
    }
}

async function login(email, password, apiKey) {
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ email, password, apiKey })
        });

        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Login failed');
        }

        isAuthenticated = true;
        updateAccessSectionUI(true);
        return true;
    } catch (e) {
        console.error('Login error:', e);
        updateAccessSectionUI(false);
        throw e;
    }
}

async function logout() {
    try {
        await fetch('/api/auth/logout', {
            method: 'POST'
        });
        isAuthenticated = false;
        updateAccessSectionUI(false);
        
        // Clear input fields
        $('#substack-email').val('');
        $('#substack-password').val('');
        $('#openai-key').val('');
        
        // Clear cached data
        localStorage.removeItem(CACHE_KEY_ARTICLES);
        localStorage.removeItem(CACHE_KEY_SUMMARIES);
        
        return true;
    } catch (e) {
        console.error('Logout error:', e);
        return false;
    }
}

// Check if Credentials Management API is available
const isCredentialsApiAvailable = () => {
    return window.PasswordCredential && window.navigator.credentials;
};

// Secure credential management with Credentials Management API
async function saveCredentials(email, password, apiKey) {
    if (!isCredentialsApiAvailable()) {
        console.error('Credentials Management API not available');
        return false;
    }

    try {
        // Create credentials object
        const cred = new PasswordCredential({
            id: email,
            password: password,
            name: email,
            iconURL: window.location.origin + '/static/favicon.svg'
        });

        // Store the OpenAI API key separately
        sessionStorage.setItem('openai_api_key', apiKey);

        // Store credentials
        await navigator.credentials.store(cred);
        
        // Prevent silent access to force re-authentication next time
        await navigator.credentials.preventSilentAccess();
        
        return true;
    } catch (e) {
        console.error('Error saving credentials:', e);
        return false;
    }
}

async function getCredentials() {
    if (!isCredentialsApiAvailable()) {
        console.error('Credentials Management API not available');
        return null;
    }

    try {
        // Request stored credentials
        const cred = await navigator.credentials.get({
            password: true,
            mediation: 'required' // Always show the chooser
        });

        console.log('Retrieved credentials:', cred); // Debug log

        if (cred && cred instanceof PasswordCredential) {
            // Get the stored API key
            const apiKey = sessionStorage.getItem('openai_api_key');
            
            return {
                email: cred.id,
                password: cred.password,
                apiKey: apiKey
            };
        }
        return null;
    } catch (e) {
        console.error('Error getting credentials:', e);
        return null;
    }
}

async function clearCredentials() {
    if (!isCredentialsApiAvailable()) {
        console.error('Credentials Management API not available');
        return false;
    }

    try {
        // Prevent silent access to force re-authentication
        await navigator.credentials.preventSilentAccess();
        
        // Clear API key from session storage
        sessionStorage.removeItem('openai_api_key');
        
        // Clear input fields
        $('#substack-email').val('');
        $('#substack-password').val('');
        $('#openai-key').val('');
        
        return true;
    } catch (e) {
        console.error('Error clearing credentials:', e);
        return false;
    }
}

async function loadCredentials() {
    try {
        console.log('Loading credentials...'); // Debug log
        const credentials = await getCredentials();
        console.log('Loaded credentials:', credentials); // Debug log
        
        if (credentials) {
            $('#substack-email').val(credentials.email);
            $('#substack-password').val(credentials.password);
            $('#openai-key').val(credentials.apiKey);
            return true;
        }
        return false;
    } catch (e) {
        console.error('Error loading credentials:', e);
        return false;
    }
}

// Encryption functions using Web Crypto API
async function generateKey() {
    return await window.crypto.subtle.generateKey(
        {
            name: 'AES-GCM',
            length: 256
        },
        true,
        ['encrypt', 'decrypt']
    );
}

async function getOrCreateKey() {
    const keyString = sessionStorage.getItem('encryptionKey');
    if (keyString) {
        const keyBuffer = new Uint8Array(JSON.parse(keyString)).buffer;
        return await window.crypto.subtle.importKey(
            'raw',
            keyBuffer,
            'AES-GCM',
            true,
            ['encrypt', 'decrypt']
        );
    }
    
    const key = await generateKey();
    const exportedKey = await window.crypto.subtle.exportKey('raw', key);
    sessionStorage.setItem('encryptionKey', JSON.stringify(Array.from(new Uint8Array(exportedKey))));
    return key;
}

async function encryptData(data) {
    const key = await getOrCreateKey();
    const iv = window.crypto.getRandomValues(new Uint8Array(12));
    const encoder = new TextEncoder();
    const encodedData = encoder.encode(JSON.stringify(data));
    
    const encryptedData = await window.crypto.subtle.encrypt(
        {
            name: 'AES-GCM',
            iv: iv
        },
        key,
        encodedData
    );
    
    return {
        iv: Array.from(iv),
        data: Array.from(new Uint8Array(encryptedData))
    };
}

async function decryptData(encryptedData) {
    const key = await getOrCreateKey();
    const iv = new Uint8Array(encryptedData.iv);
    const data = new Uint8Array(encryptedData.data);
    
    try {
        const decryptedData = await window.crypto.subtle.decrypt(
            {
                name: 'AES-GCM',
                iv: iv
            },
            key,
            data
        );
        
        const decoder = new TextDecoder();
        return JSON.parse(decoder.decode(decryptedData));
    } catch (e) {
        console.error('Decryption failed:', e);
        return null;
    }
}

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
    const currentLength = parseInt($('input[name="summary-length"]:checked').val());
    const cachedSummary = cachedSummaries[article.url];
    const hasCachedSummary = cachedSummary && cachedSummary.length === currentLength;
    
    const summaryHtml = hasCachedSummary ? `
        <div class="ai-badge">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            AI Summary
        </div>
        <p class="article-summary">${cachedSummary.text}</p>
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
                const currentLength = parseInt($('input[name="summary-length"]:checked').val());
                const cachedSummary = cachedSummaries[article.url];
                if (cachedSummary.length === currentLength) {
                    articleElement.find('.article-summary-container').html(`
                        <div class="ai-badge">
                            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                            AI Summary
                        </div>
                        <p class="article-summary">${cachedSummary.text}</p>
                    `);
                } else {
                    articleElement.find('.article-summary-container').html(`
                        <div class="summary-placeholder">
                            <div class="spinner"></div>
                            <div>Generating AI summary...</div>
                        </div>
                    `);
                    generateSummary(article, articleElement);
                }
            } else {
                articleElement.find('.article-summary-container').html(`
                    <div class="summary-placeholder">
                        <div class="spinner"></div>
                        <div>Generating AI summary...</div>
                    </div>
                `);
                generateSummary(article, articleElement);
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
        const summaryLength = parseInt($('input[name="summary-length"]:checked').val());
        
        // Check if we have a cached summary with the same length
        const cachedSummaries = getCachedSummaries();
        const cachedSummary = cachedSummaries[article.url];
        if (cachedSummary && cachedSummary.length === summaryLength) {
            // Use cached summary if length matches
            articleElement.find('.article-summary-container').html(`
                <div class="ai-badge">
                    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    AI Summary
                </div>
                <p class="article-summary">${cachedSummary.text}</p>
            `);
            return;
        }

        const response = await retryRequest(() =>
            fetch('/generate_summary', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url: article.url,
                    length: summaryLength
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

        // Cache the summary with its length
        const summaries = getCachedSummaries() || {};
        summaries[article.url] = {
            text: result.summary,
            length: summaryLength
        };
        saveToCache(CACHE_KEY_SUMMARIES, summaries);

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
    try {
        $('#progress-container').show();

        const articleLimit = parseInt($('#article-limit').val());
        
        // Save settings
        localStorage.setItem(SETTINGS_KEY, JSON.stringify({
            summaryLength: $('input[name="summary-length"]:checked').val(),
            articleLimit: articleLimit
        }));

        const response = await fetch(`/fetch_articles?limit=${articleLimit}`);
        
        if (response.status === 401) {
            isAuthenticated = false;
            updateAccessSectionUI(false);
            throw new Error('Authentication required');
        }
        
        if (!response.ok) {
            throw new Error('Failed to fetch articles');
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
        
        // Display articles with loading spinners for summaries
        result.articles.forEach((article, index) => {
            const articleElement = $(createArticleCard(article, index));
            // Replace the summary container with a loading spinner
            articleElement.find('.article-summary-container').html(`
                <div class="summary-placeholder">
                    <div class="spinner"></div>
                    <div>Generating AI summary...</div>
                </div>
            `);
            $('#articles-container').append(articleElement);
            // Generate new summary
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
        $('#progress-container').hide();
    }
}

// Document ready handler
$(document).ready(async function() {
    // Load saved settings
    loadSettings();
    
    // Check authentication status
    const authenticated = await checkAuthStatus();
    
    // Clear invalid state on input
    $('#access-section input').on('input', function() {
        $(this).removeClass('invalid');
        if ($(this).attr('id') === 'openai-key') {
            $('#openai-key-error').removeClass('visible');
        }
    });
    
    // Handle credential saving
    $('#save-credentials').click(async function() {
        // Reset any previous invalid states
        $('#access-section input').removeClass('invalid');
        $('#openai-key-error').removeClass('visible');
        
        const emailInput = $('#substack-email');
        const passwordInput = $('#substack-password');
        const apiKeyInput = $('#openai-key');
        
        const email = emailInput.val();
        const password = passwordInput.val();
        const apiKey = apiKeyInput.val();
        
        let hasError = false;
        
        if (!email) {
            emailInput.addClass('invalid');
            hasError = true;
        }
        if (!password) {
            passwordInput.addClass('invalid');
            hasError = true;
        }
        if (!apiKey) {
            apiKeyInput.addClass('invalid');
            hasError = true;
        }
        
        if (hasError) {
            return;
        }
        
        try {
            await login(email, password, apiKey);
            await refreshArticles(); // Refresh articles after successful login
        } catch (e) {
            if (e.message.includes('Invalid OpenAI API key')) {
                // Only mark the API key field as invalid
                apiKeyInput.addClass('invalid');
                $('#openai-key-error').addClass('visible');
            } else {
                // For other errors, mark email and password as invalid
                emailInput.addClass('invalid');
                passwordInput.addClass('invalid');
            }
        }
    });
    
    // Handle credential clearing
    $('#clear-credentials').click(async function() {
        await logout();
    });
    
    // Update article limit display
    $('#article-limit').on('input', function() {
        $('#article-limit-value').text($(this).val());
    });

    // Handle radio button changes for summary length
    $('input[name="summary-length"]').change(function() {
        currentSummaryLength = $(this).val();
    });

    // Handle refresh button click
    $('#refresh-button').click(async function() {
        if (!isAuthenticated) {
            alert('Please log in first');
            updateAccessSectionUI(false);
            return;
        }
        await refreshArticles();
    });

    // Load cached articles on startup if authenticated
    if (authenticated) {
        displayCachedArticles();
    }
});
