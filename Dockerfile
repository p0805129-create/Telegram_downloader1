FROM python:3.11-slim

# نصب پیش‌نیازها: ffmpeg، Node.js، git و curl
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl gnupg git && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# کلون و ساخت سرور تولید توکن PO
RUN git clone --single-branch --branch 2.0.0 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /app/bgutil-pot
WORKDIR /app/bgutil-pot/server
RUN npm ci && npx tsc

WORKDIR /app

# نصب پکیج‌های پایتون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی کردن کد ربات
COPY . .

# اجرای همزمان سرور توکن و ربات
CMD node /app/bgutil-pot/server/build/main.js & python main.py
