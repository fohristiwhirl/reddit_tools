import copy, json, queue, random, requests, threading, time, webbrowser
from bottle import request, route, run

# -------------------------------------------------------------------------------------------

INFO = json.loads(open("info.txt").read())

USER_AGENT = "{}:{}:{} (by /u/{})".format(INFO["app_platform"], INFO["app_name"], INFO["app_version"], INFO["app_author"])

# -------------------------------------------------------------------------------------------

random.seed()

def gen_random_string():
    result_list = []
    for n in range(32):
        result_list.append(random.choice("abcdefghijklmnopqrstuvwxyz1234567890"))
    result = "".join(result_list)
    return result

# -------------------------------------------------------------------------------------------

CLIENT_ID = INFO["client_id"]
CLIENT_SECRET = INFO["client_secret"]   # This doesn't exist for Apps, merely local scripts

LOCAL_PORT = 8081

RESPONSE_TYPE = "code"
STATE = gen_random_string()
REDIRECT_URI = "http://127.0.0.1:{}".format(LOCAL_PORT)
DURATION = "temporary"
SCOPE = "edit,history,read"

O_AUTH2_URL = "https://www.reddit.com/api/v1/authorize?client_id={}&response_type={}&state={}&redirect_uri={}&duration={}&scope={}".format(
        CLIENT_ID, RESPONSE_TYPE, STATE, REDIRECT_URI, DURATION, SCOPE)

CODE_POST_URL = "https://www.reddit.com/api/v1/access_token"

MAIN_URL = "https://oauth.reddit.com"

INITIAL_EXTRA_HEADERS = {'User-agent': USER_AGENT}

# -------------------------------------------------------------------------------------------

# Webserver to deal with the redirect that Reddit sends the user to during initial authentication

BOTTLE_QUEUE = queue.Queue()

@route("/", "GET")
def slash():
    error = request.query.error
    code = request.query.code
    state = request.query.state

    BOTTLE_QUEUE.put([error, code, state])

    return "<html><head><title>Result</title></head><body><p>Error: {}</p><p>Code: {}</p><p>State: {}</p></body></html>".format(
        error, code, state)

def web_server():
    run(host = "127.0.0.1", port = LOCAL_PORT, quiet = True)

# -------------------------------------------------------------------------------------------

def get_access_token():

    web_server_thread = threading.Thread(target = web_server, daemon = True)
    web_server_thread.start()

    webbrowser.open(O_AUTH2_URL)

    error, code, state = BOTTLE_QUEUE.get()

    if error:
        print("Error: {}".format(error))
        exit()

    if state != STATE:
        print("State received did not match state sent!")
        exit()

    post_data = "grant_type=authorization_code&code={}&redirect_uri={}".format(code, REDIRECT_URI)

    response = requests.post(CODE_POST_URL, data = post_data, auth = (CLIENT_ID, CLIENT_SECRET), headers = INITIAL_EXTRA_HEADERS)
    response_dict = response.json()
    token = response_dict["access_token"]
    duration = response_dict["expires_in"]

    return Token(token, duration = duration)

# -------------------------------------------------------------------------------------------

def sanitise_endpoint(endpoint):
    if len(endpoint) > 0:
        if endpoint[0] != "/":
            endpoint = "/" + endpoint
    return endpoint

# -------------------------------------------------------------------------------------------

class Token():
    def __init__(self, tokenstring, *, duration = None, expiry = None):

        if duration is None and expiry is None:
            raise ValueError

        self.tokenstring = tokenstring
        if duration:
            self.expiry = time.time() + duration
        elif expiry:
            self.expiry = expiry

    def __str__(self):
        raise NotImplementedError("__str__() method not supported by Token(); ask for .tokenstring instead, or call .display()")

    def display(self):
        return "<Token string: {}, expires: {}>".format(self.tokenstring, time.ctime(self.expiry))

    def json(self):
        return '{"token": "' + self.tokenstring + '", "expiry": ' + str(self.expiry) + '}'

class Session():

    def __init__(self):

        self.token = None
        self.verb = ""

        try:
            with open("session.txt", "r") as infile:
                dct = json.loads(infile.read())
                self.token = Token(dct["token"], expiry = dct["expiry"])
                self.verb = "Reusing old"
        except:
            print("Failed to load from session.txt")
            self.token = None

        if self.token is None or self.token.expiry < time.time() + 300:
            self.verb = "Using new"
            self.token = get_access_token()
            with open("session.txt", "w") as outfile:
                outfile.write(self.token.json())

        print()
        print("{} token: {}".format(self.verb, self.token.display()))
        print()

        self.remaining = None
        self.reset = None
        self.used = None

    def rate_limit(self):
        if self.remaining == 0:
            print("\nWaiting {} seconds for rate limit reset\n", self.reset + 2)
            time.sleep(self.reset + 2)

    def request(self, method, endpoint, *, params = {}, postdata = {}):

        self.rate_limit()
        endpoint = sanitise_endpoint(endpoint)

        out_headers = copy.copy(INITIAL_EXTRA_HEADERS)
        out_headers["Authorization"] = "bearer {}".format(self.token.tokenstring)

        if method.lower() == "get":
            response = requests.get(MAIN_URL + endpoint, params = params, headers = out_headers)
        elif method.lower() == "post":
            response = requests.post(MAIN_URL + endpoint, params = params, data = postdata, headers = out_headers)

        try:
            self.remaining = response.headers["x-ratelimit-remaining"]
            self.reset = response.headers["x-ratelimit-reset"]
            self.used = response.headers["x-ratelimit-used"]
        except:
            print("Session.request() encountered an error...")
            print(response.text)
            print("END OF REPORT from Session.request()")

        return response

    def get(self, endpoint, *, params = {}):
        response = self.request("GET", endpoint, params = params)
        return response.json()

    def post(self, endpoint, *, postdata = {}):
        response = self.request("POST", endpoint, postdata = postdata)
        return response.json()
