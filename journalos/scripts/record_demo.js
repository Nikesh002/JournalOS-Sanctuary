const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function recordDemo() {
  const outputDir = path.join(__dirname, '..', 'recordings');
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  console.log('Launching browser with video recording enabled...');
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    recordVideo: {
      dir: outputDir,
      size: { width: 1280, height: 800 }
    }
  });

  const page = await context.newPage();
  console.log('Navigating to JournalOS local frontend (http://localhost:8080)...');
  await page.goto('http://localhost:8080', { waitUntil: 'networkidle' });

  // Pacing pause
  await page.waitForTimeout(2000);

  // Turn 1: Showcase core application feature (Reflective Journaling & Mood Logging)
  const prompt1 = "I had a busy and overwhelming day balancing project deadlines, but I made progress on key goals. Can you help me reflect on this using the Reflective Journaling methodology and log my mood?";
  console.log('Typing Prompt 1 (Core Reflective Journaling)...');
  await page.type('#input', prompt1, { delay: 35 });
  await page.waitForTimeout(800);

  console.log('Submitting Prompt 1...');
  await page.click('button[type="submit"]');

  console.log('Waiting for Turn 1 response and A2UI cards...');
  await page.waitForFunction(() => {
    const bubbles = document.querySelectorAll('.msg.agent .bubble');
    if (bubbles.length < 1) return false;
    const last = bubbles[bubbles.length - 1];
    return last && last.textContent !== '…' && last.textContent.trim().length > 0;
  }, { timeout: 60000 });

  console.log('Turn 1 completed! Pausing to display Reflective Journaling card...');
  await page.waitForTimeout(5000);

  // Turn 2: Showcase Richer Prompt (Tool Call, Firestore Database Lookup & Generated Moodscape Image)
  const prompt2 = "Please list my past journal entries from Firestore, calculate my recent mood trend, and generate a serene visual moodscape image for today's entry.";
  console.log('Typing Prompt 2 (Database Lookup & Visual Moodscape Image Gen)...');
  await page.type('#input', prompt2, { delay: 35 });
  await page.waitForTimeout(800);

  console.log('Submitting Prompt 2...');
  await page.click('button[type="submit"]');

  console.log('Waiting for Turn 2 response (Firestore query + image generation)...');
  await page.waitForFunction(() => {
    const bubbles = document.querySelectorAll('.msg.agent .bubble');
    if (bubbles.length < 2) return false;
    const last = bubbles[bubbles.length - 1];
    return last && last.textContent !== '…' && last.textContent.trim().length > 0;
  }, { timeout: 120000 });

  await page.waitForTimeout(4000);

  console.log('Turn 2 completed! Pausing to showcase rich results and visual artwork...');
  await page.waitForTimeout(7000);

  console.log('Closing browser context to finalize video recording...');
  const video = page.video();
  await context.close();
  await browser.close();

  if (video) {
    const videoPath = await video.path();
    console.log('Video recorded successfully at:', videoPath);

    // Copy video to assets directory
    const assetsDir = path.join(__dirname, '..', '..', 'assets');
    if (!fs.existsSync(assetsDir)) {
      fs.mkdirSync(assetsDir, { recursive: true });
    }
    const destPath = path.join(assetsDir, 'journalos_demo.webm');
    fs.copyFileSync(videoPath, destPath);
    console.log('Saved demo video to:', destPath);

    // Also copy to journalos/assets/
    const localAssetsDir = path.join(__dirname, '..', 'assets');
    if (!fs.existsSync(localAssetsDir)) {
      fs.mkdirSync(localAssetsDir, { recursive: true });
    }
    const localDestPath = path.join(localAssetsDir, 'journalos_demo.webm');
    fs.copyFileSync(videoPath, localDestPath);
    console.log('Saved demo video to local assets:', localDestPath);
  } else {
    console.error('No video object found!');
  }
}

recordDemo().catch(err => {
  console.error('Error during recording:', err);
  process.exit(1);
});
