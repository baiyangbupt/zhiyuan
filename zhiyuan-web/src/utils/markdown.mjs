import { marked } from 'marked';
import sanitizeHtml from 'sanitize-html';

export const renderMarkdown = (content) => sanitizeHtml(
  marked.parse(content || '', { gfm: true, breaks: true }),
  {
    allowedTags: [
      'p', 'br', 'hr', 'strong', 'em', 'del', 's', 'blockquote',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
      'pre', 'code', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    ],
    allowedAttributes: { a: ['href', 'title'], ol: ['start'], code: ['class'] },
    allowedClasses: { code: ['language-*'] },
    allowedSchemes: ['https', 'http', 'mailto'],
    allowProtocolRelative: false,
  },
);
