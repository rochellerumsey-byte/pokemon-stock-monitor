"""
Configuration for Pokemon Stock Monitor
"""

# Check interval (seconds)
# Default: 60 seconds (1 minute)
# Don't set below 30 to avoid being blocked!
CHECK_INTERVAL = 60

# Alert settings
PLAY_SOUND = True  # Play sound when stock detected
AUTO_OPEN_BROWSER = True  # Automatically open browser to product page

# Discord webhook (optional - for mobile alerts)
# To get webhook: Discord Server → Settings → Integrations → Webhooks → New Webhook
DISCORD_WEBHOOK_URL = ""  # Leave empty to disable

# Advanced settings
REQUEST_TIMEOUT = 10  # Seconds to wait for page response
DELAY_BETWEEN_CHECKS = 2  # Seconds between checking each product in list
