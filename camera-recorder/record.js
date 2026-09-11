const { spawn } = require('child_process');
const path = require('path');

const CAMERA_NAME = process.env.CAMERA_NAME || 'Integrated Camera';
const OUTPUT_DIR = process.env.OUTPUT_DIR || 'E:\\CameraRecordings';
// Segment time in seconds (900 = 15 minutes)
const SEGMENT_TIME = process.env.SEGMENT_TIME || '900';

console.log(`Starting camera recording...`);
console.log(`Camera: ${CAMERA_NAME}`);
console.log(`Output Directory: ${OUTPUT_DIR}`);
console.log(`Segment Time: ${SEGMENT_TIME} seconds`);

const outputPattern = path.join(OUTPUT_DIR, 'camera_%Y-%m-%d_%H-%M-%S.mp4');

// ffmpeg command arguments
const args = [
    '-f', 'dshow',
    '-i', `video=${CAMERA_NAME}`,
    '-c:v', 'libx264',      // Use h264 encoding
    '-preset', 'veryfast',  // Reduce CPU usage
    '-f', 'segment',        // Use segment muxer
    '-segment_time', SEGMENT_TIME,
    '-reset_timestamps', '1',
    '-strftime', '1',
    outputPattern
];

const ffmpeg = spawn('ffmpeg', args);

ffmpeg.stdout.on('data', (data) => {
    console.log(`[ffmpeg stdout]: ${data}`);
});

ffmpeg.stderr.on('data', (data) => {
    const output = data.toString();
    if (output.toLowerCase().includes('error') || output.includes('Opening')) {
        console.error(`[ffmpeg]: ${output.trim()}`);
    }
});

ffmpeg.on('close', (code) => {
    console.log(`ffmpeg process exited with code ${code}`);
    process.exit(code);
});

ffmpeg.on('error', (err) => {
    console.error('Failed to start ffmpeg. Is it installed and added to PATH?');
    console.error(err);
    process.exit(1);
});

// Handle graceful shutdown from PM2
process.on('SIGINT', () => {
    console.log('Received SIGINT. Shutting down ffmpeg gracefully...');
    ffmpeg.kill('SIGINT');
    setTimeout(() => {
        process.exit(0);
    }, 5000);
});
