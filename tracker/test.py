import requests

url = "https://api.snitcher.com/radar/operator/v1/webhooks"

payload = { "delivery": {
        "webhook_url": "https://qla-backend.zipeline.com/api/tracker/webhook/"
    } }
headers = {
    "Authorization": "Bearer 511|E2434QIIwDUYauvxr0NsD37QWg01sfgU1vXuJo24849fb401",
    "Content-Type": "application/json"
}

response = requests.patch(url, json=payload, headers=headers)

print(response.text)