/**
 * PostCSS configuration.
 *
 * Enables Tailwind v4 for the app. Only the intake stylesheet
 * (app/intake/intake.css) imports Tailwind, so existing pages - which import no
 * CSS at all and style themselves inline - are unaffected.
 *
 * autoprefixer is not listed: Tailwind v4 handles vendor prefixing itself, and
 * running both would duplicate work.
 */
const config = {
  plugins: {
    "@tailwindcss/postcss": {}
  }
};

export default config;
