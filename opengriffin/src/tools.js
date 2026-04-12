// ══════════════════════════════════════════
// OpenGriffin — Built-in Tools
// Tools Claude can call via function calling.
// These are always available regardless of agent.
// ══════════════════════════════════════════

export const BUILTIN_TOOLS = [
  {
    name: 'remember',
    description: 'Store a fact or preference about the user for future reference. Use this whenever the user shares personal info, preferences, or important context you should remember.',
    input_schema: {
      type: 'object',
      properties: {
        key: { type: 'string', description: 'Short identifier (e.g., "name", "company", "preferred_tone")' },
        value: { type: 'string', description: 'The fact to remember' },
        category: {
          type: 'string',
          enum: ['personal', 'work', 'preferences', 'contacts', 'general'],
          description: 'Category for organization'
        },
      },
      required: ['key', 'value'],
    },
  },
  {
    name: 'recall',
    description: 'Retrieve a stored fact about the user. Use this to check what you know about them.',
    input_schema: {
      type: 'object',
      properties: {
        key: { type: 'string', description: 'The key to look up' },
      },
      required: ['key'],
    },
  },
  {
    name: 'recall_all',
    description: 'Retrieve all stored memories about the user, optionally filtered by category.',
    input_schema: {
      type: 'object',
      properties: {
        category: {
          type: 'string',
          enum: ['personal', 'work', 'preferences', 'contacts', 'general'],
          description: 'Filter by category (omit for all)'
        },
      },
    },
  },
  {
    name: 'create_task',
    description: 'Create a task or reminder for the user. Can include a cron schedule for recurring tasks.',
    input_schema: {
      type: 'object',
      properties: {
        title: { type: 'string', description: 'Task title' },
        description: { type: 'string', description: 'Detailed description' },
        priority: { type: 'integer', minimum: 1, maximum: 5, description: '1=critical, 5=low' },
        due_at: { type: 'string', description: 'ISO datetime for when this is due (optional)' },
        cron: { type: 'string', description: 'Cron expression for recurring tasks (e.g., "0 9 * * 1" for every Monday 9am)' },
      },
      required: ['title'],
    },
  },
  {
    name: 'list_tasks',
    description: 'List the user\'s pending tasks.',
    input_schema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'complete_task',
    description: 'Mark a task as completed.',
    input_schema: {
      type: 'object',
      properties: {
        task_id: { type: 'string', description: 'The task ID to complete' },
        result: { type: 'string', description: 'Completion notes or result' },
      },
      required: ['task_id'],
    },
  },
  {
    name: 'get_current_time',
    description: 'Get the current date and time in the user\'s timezone.',
    input_schema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'get_stats',
    description: 'Get statistics about the user\'s usage — messages sent, memories stored, tasks completed.',
    input_schema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'switch_agent',
    description: 'Switch to a different agent template. Available agents: chief-of-staff, inbox-ops, lead-hawk, content-engine, custom.',
    input_schema: {
      type: 'object',
      properties: {
        agent_id: {
          type: 'string',
          description: 'The agent to switch to'
        },
      },
      required: ['agent_id'],
    },
  },
  {
    name: 'generate_image',
    description: 'Generate an AI image from a text prompt. Use when the user asks to create, draw, generate, or make an image, picture, photo, illustration, or artwork.',
    input_schema: {
      type: 'object',
      properties: {
        prompt: { type: 'string', description: 'Detailed description of the image to generate' },
        model: {
          type: 'string',
          enum: ['flux-pro', 'flux-dev', 'flux-schnell', 'recraft', 'ideogram', 'stable-diff'],
          description: 'Image model. flux-schnell is fastest/cheapest, flux-pro is highest quality. Default: flux-schnell'
        },
      },
      required: ['prompt'],
    },
  },
  {
    name: 'generate_video',
    description: 'Generate an AI video from a text prompt. Use when the user asks to create a video, animation, or clip.',
    input_schema: {
      type: 'object',
      properties: {
        prompt: { type: 'string', description: 'Description of the video to generate' },
        model: {
          type: 'string',
          enum: ['kling', 'hailuo', 'wan', 'ltx'],
          description: 'Video model. ltx is cheapest, kling is highest quality. Default: ltx'
        },
        duration: { type: 'integer', minimum: 3, maximum: 15, description: 'Video duration in seconds (default: 5)' },
      },
      required: ['prompt'],
    },
  },
];

/**
 * Create a tool handler that executes built-in tools against the memory store.
 */
export function createToolHandler(memory, userId, agentId, mediaGenerator = null) {
  return async (toolName, input) => {
    switch (toolName) {
      case 'remember':
        memory.remember(userId, agentId, input.key, input.value, input.category || 'general');
        memory.log(userId, agentId, 'remember', `${input.key}: ${input.value}`);
        return { success: true, message: `Remembered: ${input.key} = ${input.value}` };

      case 'recall': {
        const value = memory.recall(userId, agentId, input.key);
        return value ? { found: true, key: input.key, value } : { found: false, key: input.key };
      }

      case 'recall_all': {
        const memories = memory.recallAll(userId, agentId, input.category || null);
        return { count: memories.length, memories };
      }

      case 'create_task': {
        const taskId = memory.createTask(userId, agentId, input.title, input.description || '', {
          priority: input.priority,
          dueAt: input.due_at,
          cron: input.cron,
        });
        memory.log(userId, agentId, 'create_task', input.title);
        return { success: true, task_id: taskId, title: input.title };
      }

      case 'list_tasks': {
        const tasks = memory.getPendingTasks(userId);
        return {
          count: tasks.length,
          tasks: tasks.map(t => ({
            id: t.id,
            title: t.title,
            priority: t.priority,
            status: t.status,
            due_at: t.due_at,
            cron: t.cron_expression,
          })),
        };
      }

      case 'complete_task':
        memory.completeTask(input.task_id, input.result || '');
        memory.log(userId, agentId, 'complete_task', input.task_id);
        return { success: true, task_id: input.task_id };

      case 'get_current_time': {
        const tz = process.env.SYSTEM_TIMEZONE || 'America/Chicago';
        const now = new Date().toLocaleString('en-US', { timeZone: tz, dateStyle: 'full', timeStyle: 'long' });
        return { timezone: tz, datetime: now };
      }

      case 'get_stats':
        return memory.getStats(userId);

      case 'switch_agent':
        return { success: true, switched_to: input.agent_id };

      case 'generate_image': {
        if (!mediaGenerator) return { error: 'Image generation not configured. Add FAL_API_KEY to .env' };
        try {
          const result = await mediaGenerator.generateImage(input.prompt, input.model || 'flux-schnell');
          return { success: true, image_url: result.url, model: result.model, cost: `$${result.cost.toFixed(3)}` };
        } catch (err) { return { error: `Image generation failed: ${err.message}` }; }
      }

      case 'generate_video': {
        if (!mediaGenerator) return { error: 'Video generation not configured. Add FAL_API_KEY to .env' };
        try {
          const result = await mediaGenerator.generateVideo(input.prompt, input.model || 'ltx', { duration: input.duration || 5 });
          return { success: true, video_url: result.url, model: result.model, cost: `$${result.cost.toFixed(3)}` };
        } catch (err) { return { error: `Video generation failed: ${err.message}` }; }
      }

      default:
        return { error: `Unknown tool: ${toolName}` };
    }
  };
}
