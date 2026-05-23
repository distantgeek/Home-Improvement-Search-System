// ESLint 9 flat config — covers inline <script> in index.html
// OWASP ASVS Level 2 + NIST SP 800-53 SI-10 (input validation)
// Tools: eslint-plugin-security (OWASP mapped), eslint-plugin-no-unsanitized (XSS)
import js from '@eslint/js';
import security from 'eslint-plugin-security';
import noUnsanitized from 'eslint-plugin-no-unsanitized';
import pluginHtml from 'eslint-plugin-html';
import globals from 'globals';

export default [
  // ── HTML files: extract and lint inline <script> blocks ──────────────────
  {
    files: ['**/*.html'],
    plugins: {
      html: pluginHtml,
    },
  },

  // ── Security and standards rules applied to all JS (inline + standalone) ─
  {
    files: ['**/*.html', '**/*.js'],
    ignores: ['node_modules/**', 'playwright-report/**', 'test-results/**'],
    plugins: {
      security,
      'no-unsanitized': noUnsanitized,
    },
    languageOptions: {
      ecmaVersion: 2022,
      globals: {
        ...globals.browser,
      },
    },
    rules: {
      // ── ESLint recommended ───────────────────────────────────────────────
      ...js.configs.recommended.rules,

      // ── OWASP A03: Injection ─────────────────────────────────────────────
      'no-eval': 'error',              // CWE-95: eval injection
      'no-new-func': 'error',          // CWE-95: Function() constructor
      'no-implied-eval': 'error',      // CWE-95: setTimeout("string")
      'no-script-url': 'error',        // CWE-79: javascript: URLs

      // ── OWASP A03/A01: XSS and DOM injection ─────────────────────────────
      'no-unsanitized/method': ['error', {
        escape: { taggedTemplates: ['escHtml'] },
      }],
      'no-unsanitized/property': ['error', {
        escape: { taggedTemplates: ['escHtml'] },
      }],

      // ── OWASP security plugin (maps to CWE / SANS Top 25) ───────────────
      ...security.configs.recommended.rules,

      // ── Code quality (NIST CM-7: least functionality) ────────────────────
      'no-with': 'error',
      'no-var': 'warn',
      'prefer-const': 'warn',
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      'no-console': 'warn',

      // ── Allow patterns used intentionally in index.html ──────────────────
      // innerHTML is used extensively for rendering — flagged by no-unsanitized
      // but all user-visible data passes through escHtml() first.
      // Disable the catch-all security/detect-object-injection for bracket notation
      // which produces too many false positives on array indexing.
      'security/detect-object-injection': 'off',
    },
  },
];
