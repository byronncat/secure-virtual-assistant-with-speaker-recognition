// AudioWorklet processor: runs on the dedicated audio rendering thread.
// Receives Float32 PCM directly from the mic (at the device's native
// sample rate, commonly 48kHz) and forwards each 128-sample chunk to the
// main thread, where they're buffered, concatenated, and converted to
// 16-bit PCM for upload.
//
// Served from /public so it can be loaded via:
//   audioContext.audioWorklet.addModule("/pcm-worklet-processor.js")

class PCMWorkletProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    const channel = input && input[0];

    if (channel && channel.length > 0) {
      // Copy the buffer -- the Float32Array reference is reused by the
      // audio engine on the next render quantum.
      this.port.postMessage(channel.slice(0));
    }

    return true; // keep the processor alive
  }
}

registerProcessor("pcm-processor", PCMWorkletProcessor);