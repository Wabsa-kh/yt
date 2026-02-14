name: Auto YouTube Upload (Tor Powered)

on:
  schedule:
    - cron: "0 */4 * * *" # Runs every 4 hours
  workflow_dispatch:      # Allows you to click "Run" manually

permissions:
  contents: write

jobs:
  run_bot:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install Tor and FFmpeg
        run: |
          sudo apt-get update
          sudo apt-get install -y tor ffmpeg
          sudo service tor start
          sleep 10 # Wait for Tor to initialize its IP

      - name: Install Dependencies
        run: pip install -r requirements.txt

      - name: Create Cookies File
        run: echo "${{ secrets.YT_COOKIES }}" > cookies.txt

      - name: Run Uploader
        env:
          YT_CLIENT_ID: ${{ secrets.YT_CLIENT_ID }}
          YT_CLIENT_SECRET: ${{ secrets.YT_CLIENT_SECRET }}
          YT_REFRESH_TOKEN: ${{ secrets.YT_REFRESH_TOKEN }}
        run: python main.py

      - name: Save State
        if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add state/*.json
          git commit -m "Update state logs [skip ci]" || echo "No changes"
          git push
