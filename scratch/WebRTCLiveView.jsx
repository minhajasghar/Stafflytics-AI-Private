import React, { useEffect, useRef, useState } from 'react';

/**
 * WebRTCLiveView Component
 * Plays a real-time WebRTC (WHEP) video stream from a MediaMTX server.
 * Includes automatic reconnection handling and a placeholder fallback.
 * 
 * @param {string} streamPath - MediaMTX path name (e.g. 'cam')
 * @param {string} mediaMtxHost - MediaMTX hostname/IP (defaults to current location hostname)
 * @param {string} mediaMtxPort - MediaMTX WHEP port (defaults to '8889')
 */
const WebRTCLiveView = ({ streamPath = 'cam', mediaMtxHost = '', mediaMtxPort = '8889' }) => {
  const videoRef = useRef(null);
  const peerConnectionRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  
  const [status, setStatus] = useState('Initializing...');
  const [statusColor, setStatusColor] = useState('#94a3b8');
  const [isLive, setIsLive] = useState(false);
  const [errorCount, setErrorCount] = useState(0);

  const updateStatus = (text, color, live = false) => {
    setStatus(text);
    setStatusColor(color);
    setIsLive(live);
  };

  const startStream = async () => {
    // Clear any existing connections and timeouts
    stopStream();
    
    const video = videoRef.current;
    if (!video) return;

    updateStatus('Connecting WebRTC...', '#3b82f6');

    try {
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
      });
      peerConnectionRef.current = pc;

      // Add a transceiver to receive video
      pc.addTransceiver('video', { direction: 'recvonly' });

      // When track is received, bind to HTML5 video tag
      pc.ontrack = (event) => {
        if (event.streams && event.streams[0]) {
          video.srcObject = event.streams[0];
          updateStatus('WebRTC Live', '#22c55e', true);
          setErrorCount(0); // Reset errors on successful connection
          
          video.play().catch(e => {
            console.warn('[WebRTC] Autoplay blocked, user interaction required:', e);
          });
        }
      };

      // Detect ICE connection drops
      pc.oniceconnectionstatechange = () => {
        const state = pc.iceConnectionState;
        console.log(`[WebRTC] ICE Connection State: ${state}`);
        if (state === 'disconnected' || state === 'failed') {
          handleReconnect('Connection Lost (Reconnecting...)');
        }
      };

      // Create WebRTC Offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Wait for local ICE gathering to complete before sending SDP to MediaMTX
      await new Promise((resolve) => {
        if (pc.iceGatheringState === 'complete') {
          resolve();
        } else {
          const checkState = () => {
            if (pc.iceGatheringState === 'complete') {
              pc.removeEventListener('icegatheringstatechange', checkState);
              resolve();
            }
          };
          pc.addEventListener('icegatheringstatechange', checkState);
        }
      });

      // Negotiate with MediaMTX WHEP endpoint
      const host = mediaMtxHost || window.location.hostname;
      const whepUrl = `http://${host}:${mediaMtxPort}/${streamPath}/whep`;

      const response = await fetch(whepUrl, {
        method: 'POST',
        body: pc.localDescription.sdp,
        headers: { 'Content-Type': 'application/sdp' }
      });

      if (!response.ok) {
        throw new Error(`WHEP endpoint returned status code ${response.status}`);
      }

      const answerSdp = await response.text();
      await pc.setRemoteDescription(
        new RTCSessionDescription({
          type: 'answer',
          sdp: answerSdp
        })
      );

    } catch (err) {
      console.error('[WebRTC WHEP Error]', err);
      handleReconnect('Stream Offline (Reconnecting...)');
    }
  };

  const handleReconnect = (msg) => {
    updateStatus(msg, '#ef4444', false);
    
    // Clear video element src
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    
    // Exponential backoff retry (between 3s and 15s)
    const delay = Math.min(3000 + errorCount * 2000, 15000);
    setErrorCount(prev => prev + 1);
    
    clearTimeout(reconnectTimeoutRef.current);
    reconnectTimeoutRef.current = setTimeout(() => {
      startStream();
    }, delay);
  };

  const stopStream = () => {
    clearTimeout(reconnectTimeoutRef.current);
    if (peerConnectionRef.current) {
      try {
        peerConnectionRef.current.close();
      } catch (e) {}
      peerConnectionRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  };

  // Mount/Unmount logic
  useEffect(() => {
    startStream();
    return () => {
      stopStream();
    };
  }, [streamPath, mediaMtxHost, mediaMtxPort]);

  return (
    <div style={styles.container}>
      {/* HTML5 Native Video Tag */}
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        style={{
          ...styles.videoPlayer,
          display: isLive ? 'block' : 'none'
        }}
      />

      {/* Fallback black canvas showing loading/offline status */}
      {!isLive && (
        <div style={styles.fallbackCanvas}>
          <div style={styles.spinner} />
          <div style={styles.fallbackText}>{status}</div>
        </div>
      )}

      {/* Premium WebRTC Status Badge */}
      <div style={{
        ...styles.statusBadge,
        opacity: isLive ? 0.85 : 1
      }}>
        <span style={{
          ...styles.statusDot,
          backgroundColor: statusColor,
          boxShadow: `0 0 8px ${statusColor}`
        }} />
        <span>{status}</span>
      </div>
    </div>
  );
};

// Inline premium CSS styles
const styles = {
  container: {
    position: 'relative',
    width: '100%',
    height: '100%',
    background: '#0f172a',
    borderRadius: '12px',
    overflow: 'hidden',
    border: '1px solid rgba(255,255,255,0.05)',
    boxShadow: '0 8px 30px rgba(0,0,0,0.3)',
    aspectRatio: '16/9'
  },
  videoPlayer: {
    width: '100%',
    height: '100%',
    objectFit: 'fill'
  },
  fallbackCanvas: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#0f172a',
    gap: '12px'
  },
  fallbackText: {
    color: '#94a3b8',
    fontSize: '0.85rem',
    fontWeight: '600'
  },
  spinner: {
    width: '24px',
    height: '24px',
    border: '3px solid rgba(255,255,255,0.1)',
    borderTopColor: '#3b82f6',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite'
  },
  statusBadge: {
    position: 'absolute',
    top: '15px',
    left: '15px',
    background: 'rgba(15, 23, 42, 0.85)',
    color: '#ffffff',
    padding: '6px 12px',
    borderRadius: '30px',
    fontSize: '0.75rem',
    fontWeight: '700',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    backdropFilter: 'blur(6px)',
    border: '1px solid rgba(255,255,255,0.1)',
    transition: 'opacity 0.3s ease'
  },
  statusDot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    display: 'inline-block'
  }
};

export default WebRTCLiveView;
