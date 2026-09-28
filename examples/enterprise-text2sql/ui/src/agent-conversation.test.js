import assert from 'node:assert/strict';
import test from 'node:test';
import { createAgentConversation } from './agent-conversation.js';

test('keeps follow-up questions and answers in one conversation', () => {
  const conversation = createAgentConversation(() => 'conversation-1');
  conversation.begin('华南区第二季度销售额是多少？');
  conversation.applyEvent({ type: 'final', content: '销售额为 770 元。' });
  conversation.applyEvent({ type: 'done' });

  conversation.begin('其中哪个城市退款率最高？');
  conversation.applyEvent({ type: 'final', content: '深圳最高。' });

  assert.equal(conversation.conversationId, 'conversation-1');
  assert.deepEqual(
    conversation.turns.map(({ question, answer }) => [question, answer]),
    [
      ['华南区第二季度销售额是多少？', '销售额为 770 元。'],
      ['其中哪个城市退款率最高？', '深圳最高。'],
    ],
  );
});

test('resets transcript and starts a new conversation for a new identity scope', () => {
  let id = 0;
  const conversation = createAgentConversation(() => `conversation-${++id}`);
  conversation.begin('华南区第二季度销售额是多少？');
  conversation.applyEvent({ type: 'final', content: '销售额为 770 元。' });

  conversation.reset();

  assert.equal(conversation.conversationId, 'conversation-2');
  assert.deepEqual(conversation.turns, []);
  assert.equal(conversation.activeTurn, null);
});
