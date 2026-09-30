import { useI18n } from '../i18n';

/**
 * Espaço reservado para o chat do assistente (Backend 2, de IA, ainda não existe).
 * Não faz nenhuma chamada de rede: quando o Backend 2 existir, a conversa entra aqui.
 */
export function Assistant({ open, onToggle }: { open?: boolean; onToggle?: () => void }) {
  const { t } = useI18n();
  return (
    <>
      <button type="button" className="assistant-fab" onClick={onToggle} aria-expanded={open} aria-controls="assistant-panel">
        {open ? '✕' : '💬'}
        <span>{t('nav.assistant')}</span>
      </button>
      {open && (
        <aside id="assistant-panel" className="assistant-panel" aria-label={t('assistant.title')}>
          <header>
            <strong>{t('assistant.title')}</strong>
            <button type="button" className="btn btn-ghost btn-small" onClick={onToggle} aria-label={t('common.close')}>
              ✕
            </button>
          </header>
          <div className="assistant-body">
            <div className="bubble">{t('assistant.text')}</div>
          </div>
          <form className="assistant-input" onSubmit={(e) => e.preventDefault()}>
            <input placeholder={t('assistant.placeholder')} disabled aria-disabled />
            <button className="btn btn-primary btn-small" disabled title={t('assistant.soon')}>
              ➤
            </button>
          </form>
          <small className="muted center">{t('assistant.soon')}</small>
        </aside>
      )}
    </>
  );
}
