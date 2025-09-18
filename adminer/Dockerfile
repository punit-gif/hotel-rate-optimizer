# Adminer via PHP built-in server, binds to $PORT (works on Railway)
FROM php:8.2-cli

# Add Postgres driver for PHP so Adminer can connect to Railway Postgres
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq-dev ca-certificates wget \
 && docker-php-ext-install pdo_pgsql \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pin Adminer for reproducible builds
ENV ADMINER_VERSION=4.8.1
RUN wget -O /app/adminer.php https://github.com/vrana/adminer/releases/download/v${ADMINER_VERSION}/adminer-${ADMINER_VERSION}.php

# Small index that redirects to adminer.php, optionally pre-filling server from env
COPY index.php /app/index.php

# Railway injects $PORT; default to 8080 for local
ENV PORT=8080
EXPOSE 8080

CMD ["sh","-c","php -S 0.0.0.0:${PORT} -t /app"]
