const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const util = require('util');

const execPromise = util.promisify(exec);
const readdir = util.promisify(fs.readdir);
const stat = util.promisify(fs.stat);
const unlink = util.promisify(fs.unlink);

const DRIVE_LETTER = process.env.DRIVE_LETTER || 'E:';
const TARGET_DIR = process.env.OUTPUT_DIR || 'E:\\CameraRecordings';
// 850 GB in bytes
const MAX_USED_BYTES = parseFloat(process.env.MAX_USED_GB || '850') * 1024 * 1024 * 1024;
// Poll every 5 minutes by default
const CHECK_INTERVAL_MS = parseInt(process.env.CHECK_INTERVAL_MS || '300000', 10);

async function getDriveUsage() {
    try {
        // wmic logicaldisk get size,freespace /format:csv
        const { stdout } = await execPromise(`wmic logicaldisk where "DeviceID='${DRIVE_LETTER}'" get size,freespace /format:csv`);
        const lines = stdout.trim().split('\n').filter(line => line.trim().length > 0);
        if (lines.length > 1) {
            // Node,FreeSpace,Size
            const parts = lines[1].split(',');
            const freeSpace = parseInt(parts[1], 10);
            const totalSize = parseInt(parts[2], 10);
            const usedSpace = totalSize - freeSpace;
            return { usedSpace, totalSize, freeSpace };
        }
    } catch (err) {
        console.error('Error checking drive usage:', err);
    }
    return null;
}

async function cleanupOldestFiles() {
    try {
        const usage = await getDriveUsage();
        if (!usage) return;

        console.log(`[Disk Check] Used: ${(usage.usedSpace / 1024 / 1024 / 1024).toFixed(2)} GB / Limit: ${(MAX_USED_BYTES / 1024 / 1024 / 1024).toFixed(2)} GB`);

        if (usage.usedSpace > MAX_USED_BYTES) {
            console.log('Threshold exceeded! Starting cleanup...');
            
            // Get all mp4 files
            const files = await readdir(TARGET_DIR);
            const mp4Files = files.filter(f => f.endsWith('.mp4'));
            
            if (mp4Files.length === 0) {
                console.log('No video files found to delete.');
                return;
            }

            // Get stats and sort by modification time (oldest first)
            const fileStats = await Promise.all(
                mp4Files.map(async (file) => {
                    const filePath = path.join(TARGET_DIR, file);
                    const fileStat = await stat(filePath);
                    return { filePath, mtime: fileStat.mtime.getTime(), size: fileStat.size };
                })
            );

            fileStats.sort((a, b) => a.mtime - b.mtime);

            let currentUsed = usage.usedSpace;
            let deletedCount = 0;

            for (const file of fileStats) {
                if (currentUsed <= MAX_USED_BYTES) {
                    break;
                }
                
                try {
                    await unlink(file.filePath);
                    console.log(`Deleted: ${file.filePath}`);
                    currentUsed -= file.size;
                    deletedCount++;
                } catch (err) {
                    console.error(`Failed to delete ${file.filePath}:`, err);
                }
            }

            console.log(`Cleanup finished. Deleted ${deletedCount} files.`);
        }
    } catch (err) {
        console.error('Error during cleanup routine:', err);
    }
}

// Start polling
console.log(`Starting cleanup service. Monitoring ${DRIVE_LETTER} (Limit: ${MAX_USED_BYTES / 1024 / 1024 / 1024} GB) every ${CHECK_INTERVAL_MS / 1000}s`);
cleanupOldestFiles();
setInterval(cleanupOldestFiles, CHECK_INTERVAL_MS);
