FROM python:3.12-slim

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Download React, ReactDOM and Babel standalone locally so agents work without CDN
RUN python3 -c "\
from urllib.request import urlretrieve; \
import os; os.makedirs('/app/static/js', exist_ok=True); \
urlretrieve('https://cdn.jsdelivr.net/npm/react@18.2.0/umd/react.production.min.js', '/app/static/js/react.min.js'); \
urlretrieve('https://cdn.jsdelivr.net/npm/react-dom@18.2.0/umd/react-dom.production.min.js', '/app/static/js/react-dom.min.js'); \
urlretrieve('https://cdn.jsdelivr.net/npm/@babel/standalone@7.23.10/babel.min.js', '/app/static/js/babel.min.js'); \
print('JS libs downloaded OK') \
"

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
