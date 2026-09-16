# Общие настройки передачи запроса в Django. Заголовки X-Forwarded-* нужны,
# чтобы Django знал настоящий адрес клиента и протокол (http или https).
proxy_pass http://django;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_redirect off;
