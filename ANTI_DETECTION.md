# 🛡️ Anti-Detection Guide

## How Sites Block Bots

### 1. **Rate Limiting**
- **Problem**: Too many requests too fast
- **Detection**: "429 Too Many Requests" or temporary IP ban
- **Solution**: Increase `CHECK_INTERVAL` in config.py

### 2. **Bot Detection**
- **Problem**: Site recognizes automated traffic
- **Signs**: Captchas, "Access Denied", different content than browser
- **Solution**: User-agent rotation (already built-in!)

### 3. **Caching**
- **Problem**: Getting old data instead of fresh stock status
- **Signs**: Status doesn't change even after restock
- **Solution**: Cache-busting (already built-in!)

## Built-in Protections

✅ **User-Agent Rotation** - Rotates between 5 different browsers
✅ **Cache Busting** - Adds timestamp to URL to bypass cache
✅ **Random Timing** - Varies check intervals ±20%
✅ **Random Delays** - 1.5-3.5 seconds between products
✅ **Respectful Interval** - Default 60 seconds (not aggressive)

## If You Get Blocked

### Symptoms:
- HTTP 403 (Forbidden)
- HTTP 429 (Too Many Requests)
- Captchas appearing
- "Access Denied" errors

### Solutions:

#### 1. **Increase Interval** (Easiest)
```python
# config.py
CHECK_INTERVAL = 120  # 2 minutes instead of 1
```

#### 2. **Use VPN** (Rotate IP)
- Connect to VPN
- Restart bot
- Your IP address changes = fresh start

#### 3. **Wait It Out**
- Stop bot for 1-2 hours
- Sites usually reset rate limits
- Resume with higher interval

#### 4. **Use Proxies** (Advanced)
Add to `check_stock()` function:
```python
proxies = {
    'http': 'http://proxy-server:port',
    'https': 'https://proxy-server:port'
}
response = requests.get(url, headers=get_headers(), proxies=proxies, timeout=10)
```

Free proxy lists: https://free-proxy-list.net/ (quality varies!)

#### 5. **Selenium + Real Browser** (Most Advanced)
Use actual Chrome browser instead of requests:
```bash
pip install selenium webdriver-manager
```

This is slower but looks exactly like a human browsing.

## Best Practices

### ✅ DO:
- Keep interval at 60+ seconds
- Monitor 5-10 products max
- Use during low-traffic hours (2am-6am)
- Stop if you see errors

### ❌ DON'T:
- Set interval below 30 seconds
- Monitor 50+ products
- Run multiple instances on same IP
- Ignore HTTP errors

## Store-Specific Notes

### Target
- **Rate Limit**: Moderate
- **Best Interval**: 60-90 seconds
- **Notes**: Uses Akamai bot protection

### Best Buy
- **Rate Limit**: Strict
- **Best Interval**: 90-120 seconds
- **Notes**: Strong anti-bot, may need VPN

### Pokemon Center
- **Rate Limit**: Relaxed
- **Best Interval**: 60 seconds
- **Notes**: Less strict than others

### GameStop
- **Rate Limit**: Moderate
- **Best Interval**: 60 seconds
- **Notes**: Standard protection

## Advanced: Residential Proxies

If you're serious and getting blocked:

**Paid Services** ($5-50/month):
- Bright Data (formerly Luminati)
- Smartproxy
- Oxylabs

These rotate residential IPs = looks like real people browsing.

## Captcha Handling

If you hit captchas frequently:

**Manual**: Stop bot, solve captcha in browser, resume
**Automated** (costs $$$): 
- 2Captcha API ($3 per 1000 captchas)
- Anti-Captcha
- DeathByCaptcha

## Legal Notes

- ✅ Web scraping for personal use is generally legal
- ✅ Checking stock availability is not harmful
- ❌ Don't overload servers (keep 60s+ interval)
- ❌ Don't bypass auth/paywalls
- ❌ Don't violate Terms of Service intentionally

## Monitoring Best Practices

**Optimal Setup:**
1. **5-10 products max** - More = more likely to get blocked
2. **60-90 second intervals** - Sweet spot for speed vs. detection
3. **Run on separate device** - Old laptop, Raspberry Pi, etc.
4. **Use Discord alerts** - Don't need to watch screen
5. **Monitor logs** - Check `stock_log.txt` for errors

**If Running 24/7:**
- Consider VPN with auto-rotation
- Monitor during store restock times only (Target: 6-8am ET)
- Use proxy rotation for high-value products

## Error Codes Explained

- **200**: Success! ✅
- **403**: Forbidden - you're blocked (use VPN)
- **429**: Too many requests (increase interval)
- **503**: Server overloaded (not your fault, wait)
- **404**: Product removed or wrong URL
- **Timeout**: Network issue or site too slow

## Testing Without Getting Blocked

```bash
# Test single check
python -c "from stock_monitor import *; print(check_stock('YOUR_URL'))"

# This won't trigger rate limits
```

## Summary

The bot is already configured with strong anti-detection. If you follow these rules, you'll be fine:

1. ✅ Keep 60+ second interval
2. ✅ Monitor reasonable number of products (5-10)
3. ✅ Watch for errors and adjust
4. ✅ Use VPN if needed

**Most users will NEVER get blocked with default settings!**
