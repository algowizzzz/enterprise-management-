app_name = "consilium"
app_title = "Consilium"
app_publisher = "Consilium"
app_description = "Enterprise Governance, Risk & Policy platform"
app_email = "dev@example.com"
app_license = "MIT"

# All front-end assets are vendored. Nothing is fetched from a CDN at build
# or run time, because the target environment has no internet access.
# tokens.css must precede consilium.css: the application stylesheet reads the
# custom properties the token file defines.
app_include_css = [
	"/assets/consilium/css/tokens.css",
	"/assets/consilium/css/consilium.css",
]
app_include_js = ["/assets/consilium/js/consilium.js"]

web_include_css = [
	"/assets/consilium/css/tokens.css",
	"/assets/consilium/css/consilium.css",
]
web_include_js = [
	"/assets/consilium/js/consilium.js",
	"/assets/consilium/js/consilium-table.js",
]
