# The whole suite: the newspaper's pytest (Python 3.13 through uv, the wiki
# CLI the Mac runs pinned by commit) and the base's type check, node tests
# and offline gateway probe inside the image.
test:
    npm test

# The newspaper scripts only; needs nothing but uv.
test-py:
    npm run test:py
