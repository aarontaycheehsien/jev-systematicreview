// Integration check for the locally served player and exported media.
// Run after the MP4 export has finished. No browser profile is reused.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { chromium } = require(process.env.JEV_PLAYWRIGHT_DIR || 'playwright');
const base = __dirname;
const timeline = JSON.parse(fs.readFileSync(path.join(base, 'timeline.json'), 'utf8'));
const url = process.argv[2];
if (!url) throw new Error('Provide the local player URL.');
(async () => {
  const options = { headless: true };
  if (!fs.existsSync(chromium.executablePath())) {
    const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
    if (!fs.existsSync(chrome)) throw new Error('No local Chromium runtime is available.');
    options.executablePath = chrome;
  }
  const browser = await chromium.launch(options);
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1160 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url);
    await page.waitForFunction(() => document.querySelector('video').readyState >= 1);
    const info = await page.locator('video').evaluate(v => ({ duration: v.duration, width: v.videoWidth, height: v.videoHeight, error: v.error?.message }));
    assert.equal(info.duration, 225);
    assert.equal(info.width, 1920);
    assert.equal(info.height, 1080);
    assert(!info.error);
    assert.equal(await page.locator('.chapter').count(), 6);
    assert.equal(await page.locator('.line').count(), timeline.cues.length);
    const transcript = await page.locator('.line p').allTextContents();
    assert.deepEqual(transcript, timeline.cues.map(c => c.text));
    await page.locator('.chapter[data-start="160"]').click();
    await page.waitForFunction(() => document.querySelector('video').currentTime >= 160);
    await page.locator('video').evaluate(v => v.pause());
    await page.locator('video').evaluate(v => { v.currentTime = 164; });
    await page.waitForFunction(() => {
      const v=document.querySelector('video');
      return v.currentTime>=164 && !v.seeking && v.readyState>=2;
    });
    await page.screenshot({ path: path.join(base, 'deliverables/player_desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(base, 'deliverables/player_mobile.png'), fullPage: true });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    assert(!overflow, 'Player overflows the mobile viewport.');
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(base, 'deliverables/player_check.json'), JSON.stringify({ ...info, chapters: 6, transcriptCues: 25, seeking: 'passed', mobileWidth: 390, horizontalOverflow: false, javascriptErrors: errors }, null, 2));
    console.log('Player verified: media metadata, six chapter buttons, seeking, exact transcript, and mobile layout.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
