export function createAgentConversation(createId = () => crypto.randomUUID()) {
  return {
    conversationId: createId(),
    turns: [],
    activeTurn: null,
    begin(question) {
      const turn = { question, answer: '', status: 'Agent 正在分析', error: '' };
      this.turns.push(turn);
      this.activeTurn = turn;
      return turn;
    },
    applyEvent(event) {
      if (!this.activeTurn || !event) return;
      if (event.type === 'final') this.activeTurn.answer = event.content || '';
      if (event.type === 'done') this.activeTurn.status = '分析完成';
    },
    fail(message) {
      if (!this.activeTurn) return;
      this.activeTurn.status = '请求失败';
      this.activeTurn.error = message;
    },
    reset() {
      this.turns = [];
      this.activeTurn = null;
      this.conversationId = createId();
    },
  };
}
