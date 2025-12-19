"""
Pokemon Stock Monitor
Monitors product availability across multiple retailers with instant alerts
"""

import requests
import time
import json
import os
import subprocess
import webbrowser
from datetime import datetime
from bs4 import BeautifulSoup
from config import *

# User agent to mimic real browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

def load_watchlist():
    """Load product URLs from watchlist.txt"""
    try:
        with open('watchlist.txt', 'r') as f:
            urls = []
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    urls.append(line)
            return urls
    except FileNotFoundError:
        print("❌ watchlist.txt not found. Creating template...")
        create_template_watchlist()
        return []

def create_template_watchlist():
    """Create template watchlist file"""
    template = """# Pokemon Product Watchlist
# Add product URLs (one per line)
# Lines starting with # are comments

# Example URLs (replace with real products):
# https://www.target.com/p/pokemon-tcg-prismatic-evolutions-elite-trainer-box/-/A-12345678
# https://www.bestbuy.com/site/pokemon-tcg-prismatic-evolutions-booster-bundle/6789012.p
# https://www.pokemoncenter.com/product/290-12345/pokemon-tcg-prismatic-evolutions-booster-box

# Add your product URLs below:
"""
    with open('watchlist.txt', 'w') as f:
        f.write(template)
    print("✅ Created watchlist.txt - add your product URLs and run again!")

def detect_store(url):
    """Detect which store the URL is from"""
    if 'target.com' in url:
        return 'Target'
    elif 'bestbuy.com' in url:
        return 'Best Buy'
    elif 'pokemoncenter.com' in url:
        return 'Pokemon Center'
    elif 'gamestop.com' in url:
        return 'GameStop'
    elif 'amazon.com' in url:
        return 'Amazon'
    else:
        return 'Unknown'

def check_stock(url):
    """Check if product is in stock"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code != 200:
            return {
                'in_stock': False,
                'price': None,
                'error': f'HTTP {response.status_code}'
            }
        
        soup = BeautifulSoup(response.text, 'html.parser')
        store = detect_store(url)
        
        # Store-specific detection logic
        if store == 'Target':
            return check_target(soup, response.text)
        elif store == 'Best Buy':
            return check_bestbuy(soup, response.text)
        elif store == 'Pokemon Center':
            return check_pokemon_center(soup, response.text)
        elif store == 'GameStop':
            return check_gamestop(soup, response.text)
        else:
            return check_generic(soup, response.text)
            
    except requests.exceptions.RequestException as e:
        return {
            'in_stock': False,
            'price': None,
            'error': str(e)
        }

def check_target(soup, html):
    """Check Target stock status"""
    # Look for out of stock indicators
    out_of_stock_phrases = [
        'out of stock',
        'sold out',
        'unavailable',
        'not available'
    ]
    
    html_lower = html.lower()
    
    # Check if any out of stock phrase exists
    for phrase in out_of_stock_phrases:
        if phrase in html_lower:
            return {'in_stock': False, 'price': extract_price(soup)}
    
    # Look for add to cart button
    add_to_cart = soup.find(['button', 'div'], text=lambda t: t and ('add to cart' in t.lower() or 'add to bag' in t.lower()))
    
    if add_to_cart:
        return {'in_stock': True, 'price': extract_price(soup)}
    
    return {'in_stock': False, 'price': extract_price(soup)}

def check_bestbuy(soup, html):
    """Check Best Buy stock status"""
    # Best Buy specific checks
    add_to_cart = soup.find('button', {'data-button-state': 'ADD_TO_CART'})
    
    if add_to_cart:
        return {'in_stock': True, 'price': extract_price(soup)}
    
    # Check for sold out
    if 'sold out' in html.lower() or 'coming soon' in html.lower():
        return {'in_stock': False, 'price': extract_price(soup)}
    
    return {'in_stock': False, 'price': extract_price(soup)}

def check_pokemon_center(soup, html):
    """Check Pokemon Center stock status"""
    # Check for out of stock button
    out_of_stock = soup.find(['button', 'span'], text=lambda t: t and 'out of stock' in t.lower())
    
    if out_of_stock:
        return {'in_stock': False, 'price': extract_price(soup)}
    
    # Look for add to cart
    add_to_cart = soup.find(['button'], text=lambda t: t and ('add to cart' in t.lower() or 'add to bag' in t.lower()))
    
    if add_to_cart:
        return {'in_stock': True, 'price': extract_price(soup)}
    
    return {'in_stock': False, 'price': extract_price(soup)}

def check_gamestop(soup, html):
    """Check GameStop stock status"""
    # Similar logic to other stores
    if 'not available' in html.lower() or 'out of stock' in html.lower():
        return {'in_stock': False, 'price': extract_price(soup)}
    
    add_to_cart = soup.find(['button'], text=lambda t: t and 'add to cart' in t.lower())
    
    if add_to_cart:
        return {'in_stock': True, 'price': extract_price(soup)}
    
    return {'in_stock': False, 'price': extract_price(soup)}

def check_generic(soup, html):
    """Generic stock check for unknown stores"""
    out_of_stock_phrases = ['out of stock', 'sold out', 'unavailable', 'not available']
    in_stock_phrases = ['add to cart', 'add to bag', 'buy now']
    
    html_lower = html.lower()
    
    # Check in stock first (more definitive)
    for phrase in in_stock_phrases:
        if phrase in html_lower:
            return {'in_stock': True, 'price': extract_price(soup)}
    
    # Then check out of stock
    for phrase in out_of_stock_phrases:
        if phrase in html_lower:
            return {'in_stock': False, 'price': extract_price(soup)}
    
    # Unknown status
    return {'in_stock': False, 'price': extract_price(soup), 'error': 'Unable to determine stock status'}

def extract_price(soup):
    """Try to extract price from page"""
    # Common price selectors
    price_selectors = [
        {'itemprop': 'price'},
        {'class': lambda c: c and 'price' in str(c).lower()},
        {'data-testid': lambda d: d and 'price' in str(d).lower()}
    ]
    
    for selector in price_selectors:
        price_elem = soup.find(['span', 'div', 'p'], selector)
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            # Extract just numbers and decimal
            import re
            match = re.search(r'\$?(\d+\.?\d*)', price_text)
            if match:
                return f"${match.group(1)}"
    
    return None

def send_alert(store, product_name, url, price):
    """Send alert when product is in stock"""
    print("\n" + "="*60)
    print("🚨🚨🚨 ALERT! PRODUCT IN STOCK! 🚨🚨🚨")
    print("="*60)
    print(f"\n🏪 Store: {store}")
    print(f"📦 Product: {product_name}")
    if price:
        print(f"💰 Price: {price}")
    print(f"🔗 {url}")
    print("\n" + "="*60)
    
    # Log alert
    log_message(f"🚨 IN STOCK: {store} - {product_name} - {price} - {url}")
    
    # Save to restock history
    save_restock_history(store, product_name, url, price)
    
    # Play sound
    if PLAY_SOUND:
        play_alert_sound()
    
    # Desktop notification
    send_notification(store, product_name, url)
    
    # Open browser
    if AUTO_OPEN_BROWSER:
        print("🚀 Opening browser in 3 seconds...")
        time.sleep(3)
        webbrowser.open(url)
    
    # Discord webhook
    if DISCORD_WEBHOOK_URL:
        send_discord_alert(store, product_name, url, price)

def play_alert_sound():
    """Play system alert sound (macOS)"""
    try:
        subprocess.run(['afplay', '/System/Library/Sounds/Glass.aiff'], check=False)
    except:
        pass

def send_notification(store, product, url):
    """Send macOS desktop notification"""
    try:
        title = f"🚨 {store} - IN STOCK!"
        message = f"{product}"
        subprocess.run([
            'osascript', '-e',
            f'display notification "{message}" with title "{title}" sound name "Glass"'
        ], check=False)
    except:
        pass

def send_discord_alert(store, product, url, price):
    """Send alert to Discord webhook"""
    try:
        data = {
            "content": f"🚨 **IN STOCK!**",
            "embeds": [{
                "title": f"{store} - {product}",
                "url": url,
                "color": 3066993,  # Green
                "fields": [
                    {"name": "Price", "value": price or "Unknown", "inline": True},
                    {"name": "Store", "value": store, "inline": True}
                ],
                "timestamp": datetime.utcnow().isoformat()
            }]
        }
        requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=5)
    except:
        pass

def log_message(message):
    """Log message to file"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open('stock_log.txt', 'a') as f:
        f.write(f"[{timestamp}] {message}\n")

def save_restock_history(store, product, url, price):
    """Save restock to history file"""
    try:
        # Load existing history
        if os.path.exists('restock_history.json'):
            with open('restock_history.json', 'r') as f:
                history = json.load(f)
        else:
            history = []
        
        # Add new entry
        history.append({
            'timestamp': datetime.now().isoformat(),
            'store': store,
            'product': product,
            'url': url,
            'price': price
        })
        
        # Save
        with open('restock_history.json', 'w') as f:
            json.dump(history, f, indent=2)
    except:
        pass

def extract_product_name(url):
    """Try to extract product name from URL"""
    # Simple heuristic - get part of path
    parts = url.split('/')
    for part in reversed(parts):
        if part and len(part) > 5 and not part.startswith('A-') and not part.isdigit():
            # Clean up URL encoding
            name = part.replace('-', ' ').replace('_', ' ')
            # Title case
            return name.title()[:50]  # Limit length
    return "Pokemon Product"

def main():
    """Main monitoring loop"""
    print("\n" + "="*60)
    print("🎮 POKEMON STOCK MONITOR - STARTING")
    print("="*60)
    
    # Load watchlist
    urls = load_watchlist()
    
    if not urls:
        print("\n❌ No products in watchlist. Add URLs to watchlist.txt")
        return
    
    print(f"\n🔍 Monitoring {len(urls)} product(s)")
    print(f"⏰ Check interval: {CHECK_INTERVAL} seconds")
    print(f"🔔 Alerts: {'Enabled' if PLAY_SOUND else 'Disabled'}")
    print(f"🚀 Auto-open: {'Enabled' if AUTO_OPEN_BROWSER else 'Disabled'}")
    
    # Track previous states
    previous_states = {}
    
    log_message("=== Monitor Started ===")
    
    try:
        while True:
            print("\n" + "━"*60)
            
            for url in urls:
                store = detect_store(url)
                product_name = extract_product_name(url)
                
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking: {store} - {product_name}")
                
                result = check_stock(url)
                
                if 'error' in result:
                    print(f"   ⚠️  Error: {result['error']}")
                    log_message(f"ERROR: {store} - {product_name} - {result['error']}")
                elif result['in_stock']:
                    status = "🟢 IN STOCK"
                    print(f"   {status}")
                    if result['price']:
                        print(f"   💰 Price: {result['price']}")
                    
                    # Check if this is a new stock alert (not previously in stock)
                    was_in_stock = previous_states.get(url, False)
                    if not was_in_stock:
                        send_alert(store, product_name, url, result['price'])
                    
                    previous_states[url] = True
                else:
                    status = "⭕ OUT OF STOCK"
                    print(f"   {status}")
                    if result['price']:
                        print(f"   💰 Price: {result['price']}")
                    
                    previous_states[url] = False
                
                # Small delay between checks
                time.sleep(2)
            
            print("\n" + "━"*60)
            print(f"⏳ Next check in {CHECK_INTERVAL} seconds... (Ctrl+C to stop)")
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Monitor stopped by user")
        log_message("=== Monitor Stopped ===")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        log_message(f"FATAL ERROR: {e}")

if __name__ == "__main__":
    main()
