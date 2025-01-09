# Debirdify

## Find out which of your Twitter followers have a Mastodon account

This is a simple (and experimental) web app that uses the Twitter API to find out which people you follow and searches their names and bios for things that look like Mastodon IDs, and, if that fails, checks if there are any seemingly Mastodon-related keywords in their bios.

A CSV export for import into Mastodon is also provided.


### Canonical instance

An experimental canonical instance of this *was* hosted on https://pruvisto.org/debirdify.
This instance no longer works since Twitter blocked my API access due to supposed terms-of-service violations, without every clarifying what parts of the terms of service I allegedly violated and not responding to support requests regarding the matter.

Since unpaid API access no longer exists, the entire project is probably no longer relevant.


### Implementation

This project uses Django and Python. Configuration of things like the callback URL and API keys and secrets is done with WSGI environment variables.

The Twitter authentication information is stored in a cookie for 7 days so that users do not have to re-authenticate every time they revisit the website.

The logical core of the implementation is in `main/extract_mastodon_ids.py`. Using this, you can also create a standalone application to find Mastodon IDs in account bios/names.

### Installation

Install `postgresql`, `libpq-dev`, `python3` (version >=3.9), `python3-pip`, and `python3-venv`.
Then run
```
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
```

### Database

Create a new database user `debirdify`, a database `debirdify` while also granting all privileges to the user `debirdify`.

TODO: initialisation of database

### Configuration

Environment variables being used are:
  - `DEBIRDIFY_ALLOWED_HOSTS`: a list of hosts the server will accept in the format `['host1', 'host2']`
  - `DEBIRDIFY_CONSUMER_CREDENTIALS`: Twitter consumer key and secret in the format `key:secret`
  - `DEBIRDIFY_DJANGO_SECRET`: the Django secret (not sure whether we actually need this)
  - `DEBIRDIFY_CALLBACK_URL`: the callback URL to be used by the Twitter auth
  - `DEBIRDIFY_DEBUG` (0 or 1): whether Django should run in debug mode (absolutely switch this off for production use)

In Apache, you can, for example, set them using `SetVar` in your webserver configuration.
For Nginx, you can, for example, set them by using uWSGI, adding the environment variables in an uWSGI init file.

### Running

Set up a webserver and WSGI, pointing to `debirdify/wsgi`.

### Caveats

The current implementation only looks at the first 1000 followed accounts returned by Twitter. This could easily be extended to more, although Twitter does apply some fairly harsh rate limiting.

The API requests are redone every time the page is refreshed. The rate limiting also means that if users refresh the site too often or make more than a few requests, they will get an error message about rate limiting. I don't think this can be fixed without caching results on the server, which is something I actively decided not to do for privacy reasons.

Also note that I am not very well-versed in Python and wrote this code in just a few hours without ever having written any Django before (or any other web applications in the past 10 years), so I am sure there are some aspects that are not great and not according to established best practices.

Note that if you use this software you will have to get a Twitter developer account, create your own app, get your own credentials etc. and are responsible for checking that the use of this software complies with Twitter's guidelines.


### Contact

If you have any questions or suggestions, contact [@pruvisto@graz.social](https://graz.social/@pruvisto). Pull requests are welcome, but I may be too busy to put too much work into this project. Forks/other instances of this are also very welcome.


