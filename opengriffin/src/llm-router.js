// ══════════════════════════════════════════
// OpenGriffin — LLM Router (OpenRouter)
// Single API key → 300+ models.
// OpenAI-compatible. Tool calling supported.
// ══════════════════════════════════════════

// Curated model catalog — the models we surface to users.
// OpenRouter supports 300+, but we show the best ones.
export const MODELS = {
  // ── Anthropic ──
  'claude-sonnet':   { id: 'anthropic/claude-sonnet-4',       name: 'Claude Sonnet 4',     provider: 'Anthropic',  mult: 1.0,  icon: '🟣', tools: true  },
  'claude-opus':     { id: 'anthropic/claude-opus-4',         name: 'Claude Opus 4',       provider: 'Anthropic',  mult: 3.0,  icon: '🟣', tools: true  },
  'claude-haiku':    { id: 'anthropic/claude-haiku-4.5',      name: 'Claude Haiku 4.5',    provider: 'Anthropic',  mult: 0.3,  icon: '🟣', tools: true  },
  // ── OpenAI ──
  'gpt-4o':          { id: 'openai/gpt-4o',                   name: 'GPT-4o',              provider: 'OpenAI',     mult: 1.0,  icon: '🟢', tools: true  },
  'gpt-4o-mini':     { id: 'openai/gpt-4o-mini',              name: 'GPT-4o Mini',         provider: 'OpenAI',     mult: 0.2,  icon: '🟢', tools: true  },
  'gpt-5':           { id: 'openai/gpt-5',                    name: 'GPT-5',               provider: 'OpenAI',     mult: 4.0,  icon: '🟢', tools: true  },
  // ── Google ──
  'gemini-pro':      { id: 'google/gemini-2.5-pro-preview',   name: 'Gemini 2.5 Pro',      provider: 'Google',     mult: 1.2,  icon: '🔵', tools: true  },
  'gemini-flash':    { id: 'google/gemini-2.5-flash-preview', name: 'Gemini 2.5 Flash',    provider: 'Google',     mult: 0.15, icon: '🔵', tools: true  },
  // ── DeepSeek ──
  'deepseek':        { id: 'deepseek/deepseek-chat-v3-0324',  name: 'DeepSeek V3',         provider: 'DeepSeek',   mult: 0.1,  icon: '🟠', tools: true  },
  'deepseek-r1':     { id: 'deepseek/deepseek-r1',            name: 'DeepSeek R1',         provider: 'DeepSeek',   mult: 0.5,  icon: '🟠', tools: false },
  // ── Meta ──
  'llama-4':         { id: 'meta-llama/llama-4-maverick',     name: 'Llama 4 Maverick',    provider: 'Meta',       mult: 0.3,  icon: '🦙', tools: true  },
  'llama-3.3':       { id: 'meta-llama/llama-3.3-70b-instruct', name: 'Llama 3.3 70B',     provider: 'Meta',       mult: 0.15, icon: '🦙', tools: true  },
  // ── Mistral ──
  'mistral-large':   { id: 'mistralai/mistral-large-2411',    name: 'Mistral Large',       provider: 'Mistral',    mult: 0.8,  icon: '🔶', tools: true  },
  // ── xAI ──
  'grok':            { id: 'x-ai/grok-3-mini-beta',           name: 'Grok 3 Mini',         provider: 'xAI',        mult: 0.5,  icon: '⚡', tools: true  },
  // ── Qwen ──
  'qwen':            { id: 'qwen/qwen-2.5-72b-instruct',     name: 'Qwen 2.5 72B',        provider: 'Qwen',       mult: 0.12, icon: '🔸', tools: true  },
  // ── Perplexity (search-augmented) ──
  'perplexity':      { id: 'perplexity/sonar-pro',            name: 'Perplexity Sonar Pro', provider: 'Perplexity', mult: 0.4,  icon: '🌐', tools: false },
};

export const AUTO_MODEL = 'auto';

export function getModel(key) { return MODELS[key] || MODELS['claude-sonnet']; }

export function listModels() {
  return Object.entries(MODELS).map(([key, m]) => ({ key, ...m }));
}

export function tokensToWords(tokens) { return Math.ceil(tokens * 0.75); }

export function billableWords(words, modelKey) {
  return Math.ceil(words * getModel(modelKey).mult);
}

/**
 * OpenRouter-based LLM client.
 * Single API key. OpenAI-compatible. 300+ models.
 */
export class LLMRouter {
  constructor(apiKey) {
    this.apiKey = apiKey;
    this.baseUrl = 'https://openrouter.ai/api/v1';
  }

  /**
   * Auto-select best model based on message content
   */
  _autoSelect(msg) {
    const m = msg.toLowerCase();
    if (/\b(code|debug|function|script|api|python|javascript|sql|html)\b/.test(m)) return 'gpt-4o';
    if (/\b(search|find|latest|news|current|today)\b/.test(m)) return 'perplexity';
    if (/\b(write|draft|blog|email|copy|tweet|post|newsletter|story)\b/.test(m)) return 'claude-sonnet';
    if (/\b(research|analyze|compare|report|summarize|data)\b/.test(m)) return 'gemini-flash';
    if (m.length < 60) return 'deepseek'; // cheap for short queries
    return 'claude-sonnet';
  }

  /**
   * Chat with any model via OpenRouter.
   * Handles tool-use loop for models that support it.
   */
  async chat(modelKey, systemPrompt, messages, tools = [], toolHandler = null) {
    if (modelKey === AUTO_MODEL) {
      const last = messages[messages.length - 1];
      modelKey = this._autoSelect(typeof last.content === 'string' ? last.content : '');
    }

    const model = getModel(modelKey);

    // Build OpenAI-format messages
    const apiMessages = [
      { role: 'system', content: systemPrompt },
      ...messages,
    ];

    // Build tools in OpenAI format (only if model supports them)
    const apiTools = (model.tools && tools.length > 0)
      ? tools.map(t => ({
          type: 'function',
          function: { name: t.name, description: t.description, parameters: t.input_schema },
        }))
      : undefined;

    let totalTokens = 0;
    let finalText = '';
    let currentMessages = [...apiMessages];

    // Request loop (handles tool calls)
    let maxIterations = 10;
    while (maxIterations-- > 0) {
      const body = {
        model: model.id,
        messages: currentMessages,
        max_tokens: 4096,
      };
      if (apiTools) body.tools = apiTools;

      const res = await fetch(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`,
          'HTTP-Referer': 'https://opengriffin.com',
          'X-Title': 'OpenGriffin',
        },
        body: JSON.stringify(body),
      });

      const data = await res.json();
      if (data.error) throw new Error(data.error.message || JSON.stringify(data.error));

      totalTokens += (data.usage?.total_tokens ?? 0);
      const choice = data.choices?.[0];
      if (!choice) break;

      const msg = choice.message;

      // If no tool calls, we're done
      if (!msg.tool_calls || msg.tool_calls.length === 0) {
        finalText += msg.content || '';
        break;
      }

      // Handle tool calls
      finalText += msg.content || '';
      currentMessages.push(msg);

      for (const tc of msg.tool_calls) {
        let result;
        try {
          const input = JSON.parse(tc.function.arguments);
          result = toolHandler ? await toolHandler(tc.function.name, input) : { error: 'No handler' };
        } catch (err) { result = { error: err.message }; }

        currentMessages.push({
          role: 'tool',
          tool_call_id: tc.id,
          content: JSON.stringify(result),
        });
      }
    }

    const words = tokensToWords(totalTokens);
    const billed = billableWords(words, modelKey);

    return {
      text: finalText.trim(),
      tokens: totalTokens,
      words,
      billableWords: billed,
      model: modelKey,
      modelName: model.name,
      modelIcon: model.icon,
      multiplier: model.mult,
    };
  }
}
