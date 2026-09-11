module.exports = {
  apps: [
    {
      name: 'camera-record',
      script: './record.js',
      env: {
        CAMERA_NAME: 'Integrated Camera', // CHANGE THIS TO YOUR ACTUAL CAMERA NAME
        OUTPUT_DIR: 'E:\\CameraRecordings',
        SEGMENT_TIME: '900' // 15 minutes
      },
      // Restart if it crashes
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000
    },
    {
      name: 'camera-cleanup',
      script: './cleanup.js',
      env: {
        DRIVE_LETTER: 'E:',
        OUTPUT_DIR: 'E:\\CameraRecordings',
        MAX_USED_GB: '850',
        CHECK_INTERVAL_MS: '300000' // 5 minutes
      },
      autorestart: true,
      max_restarts: 10
    }
  ]
};
