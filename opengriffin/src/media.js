// ══════════════════════════════════════════
// OpenGriffin — Media Generation (fal.ai)
// Image + Video generation. 600+ models.
// Single API key. Pay-per-use.
// ══════════════════════════════════════════

export const IMAGE_MODELS = {
  'flux-pro':      { endpoint: 'fal-ai/flux-pro/v1.1-ultra',  name: 'FLUX Pro Ultra',     cost: 0.05,  unit: 'image' },
  'flux-dev':      { endpoint: 'fal-ai/flux/dev',             name: 'FLUX Dev',           cost: 0.025, unit: 'image' },
  'flux-schnell':  { endpoint: 'fal-ai/flux/schnell',         name: 'FLUX Schnell (fast)', cost: 0.003, unit: 'image' },
  'recraft':       { endpoint: 'fal-ai/recraft-v3',           name: 'Recraft V3',         cost: 0.04,  unit: 'image' },
  'ideogram':      { endpoint: 'fal-ai/ideogram/v3',          name: 'Ideogram V3',        cost: 0.04,  unit: 'image' },
  'stable-diff':   { endpoint: 'fal-ai/stable-diffusion-v35-large', name: 'Stable Diffusion 3.5', cost: 0.04, unit: 'image' },
};

export const VIDEO_MODELS = {
  'kling':         { endpoint: 'fal-ai/kling-video/v2.1/standard/text-to-video', name: 'Kling 2.1',    costPerSec: 0.07 },
  'hailuo':        { endpoint: 'fal-ai/minimax-video/video-01',                  name: 'Hailuo',       costPerSec: 0.10 },
  'wan':           { endpoint: 'fal-ai/wan/v2.1',                                name: 'Wan 2.1',      costPerSec: 0.10 },
  'ltx':           { endpoint: 'fal-ai/ltx-video/v0.9.7',                        name: 'LTX Video',    costPerSec: 0.002 },
};

export function listImageModels() {
  return Object.entries(IMAGE_MODELS).map(([key, m]) => ({ key, ...m }));
}

export function listVideoModels() {
  return Object.entries(VIDEO_MODELS).map(([key, m]) => ({ key, ...m }));
}

/**
 * fal.ai media generation client
 */
export class MediaGenerator {
  constructor(apiKey) {
    this.apiKey = apiKey;
    this.baseUrl = 'https://queue.fal.run';
  }

  /**
   * Generate an image
   * Returns: { url, model, cost }
   */
  async generateImage(prompt, modelKey = 'flux-schnell', options = {}) {
    const model = IMAGE_MODELS[modelKey] || IMAGE_MODELS['flux-schnell'];

    const input = {
      prompt,
      image_size: options.size || 'square_hd',
      num_images: 1,
      ...(options.negativePrompt ? { negative_prompt: options.negativePrompt } : {}),
    };

    const data = await this._request(model.endpoint, input);

    const imageUrl = data.images?.[0]?.url || data.output?.url;
    if (!imageUrl) throw new Error('No image URL in response');

    return {
      url: imageUrl,
      model: model.name,
      cost: model.cost,
    };
  }

  /**
   * Generate a video
   * Returns: { url, model, cost }
   */
  async generateVideo(prompt, modelKey = 'ltx', options = {}) {
    const model = VIDEO_MODELS[modelKey] || VIDEO_MODELS['ltx'];

    const input = {
      prompt,
      duration: options.duration || 5,
      ...(options.imageUrl ? { image_url: options.imageUrl } : {}),
    };

    const data = await this._request(model.endpoint, input);

    const videoUrl = data.video?.url || data.output?.url;
    if (!videoUrl) throw new Error('No video URL in response');

    const estimatedCost = model.costPerSec * (options.duration || 5);

    return {
      url: videoUrl,
      model: model.name,
      cost: estimatedCost,
    };
  }

  /**
   * Submit request to fal.ai and poll for result
   */
  async _request(endpoint, input) {
    // Submit
    const submitRes = await fetch(`${this.baseUrl}/${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Key ${this.apiKey}`,
      },
      body: JSON.stringify(input),
    });

    const submitData = await submitRes.json();

    // If we got a direct result (synchronous), return it
    if (submitData.images || submitData.video || submitData.output) {
      return submitData;
    }

    // Otherwise, poll for result
    const requestId = submitData.request_id;
    if (!requestId) throw new Error(submitData.detail || 'Failed to submit to fal.ai');

    const statusUrl = `https://queue.fal.run/${endpoint}/requests/${requestId}/status`;
    const resultUrl = `https://queue.fal.run/${endpoint}/requests/${requestId}`;

    // Poll with exponential backoff
    let delay = 1000;
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, delay));

      const statusRes = await fetch(statusUrl, {
        headers: { 'Authorization': `Key ${this.apiKey}` },
      });
      const status = await statusRes.json();

      if (status.status === 'COMPLETED') {
        const resultRes = await fetch(resultUrl, {
          headers: { 'Authorization': `Key ${this.apiKey}` },
        });
        return await resultRes.json();
      }

      if (status.status === 'FAILED') {
        throw new Error(status.error || 'Generation failed');
      }

      delay = Math.min(delay * 1.3, 5000);
    }

    throw new Error('Generation timed out');
  }
}
