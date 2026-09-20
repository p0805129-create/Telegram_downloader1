FROM python:3.11-slim

# نصب ffmpeg و Node.js (برای اجرای سرور تولید توکن PO)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# نصب سرور تولید توکن PO
RUN npm install -g bgutil-ytdlp-pot-provider

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# اجرای همزمان سرور توکن و ربات
CMD npx bgutil-ytdlp-pot-provider & python main.py
