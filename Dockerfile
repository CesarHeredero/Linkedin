FROM python:3.12-slim

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Download React, ReactDOM and Babel standalone locally (no CDN needed at runtime).
# || true makes it non-fatal so the image builds even if network is unavailable;
# the HTML files fall back to jsDelivr CDN via onerror in that case.
RUN mkdir -p /app/static/js && \
    python3 -c "from urllib.request import urlretrieve; urlretrieve('https://cdn.jsdelivr.net/npm/react@18.2.0/umd/react.production.min.js', '/app/static/js/react.min.js'); print('react OK')" || echo "react download failed" && \
    python3 -c "from urllib.request import urlretrieve; urlretrieve('https://cdn.jsdelivr.net/npm/react-dom@18.2.0/umd/react-dom.production.min.js', '/app/static/js/react-dom.min.js'); print('react-dom OK')" || echo "react-dom download failed" && \
    python3 -c "from urllib.request import urlretrieve; urlretrieve('https://cdn.jsdelivr.net/npm/@babel/standalone@7.23.10/babel.min.js', '/app/static/js/babel.min.js'); print('babel OK')" || echo "babel download failed"

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
