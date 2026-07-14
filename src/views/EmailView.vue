<script setup>
import { useI18n } from 'vue-i18n'
import heroImage from '../assets/email-hero.png'
import logoMain from '../assets/ysLogo_transparent.png'

const { t, tm } = useI18n()

const templates = tm('email.templates') || []

const paragraphs = tm('email.paragraphs') || []

const warningItems = tm('email.warning.items') || []

const socialLinks = tm('email.social_links') || []
</script>

<template>
  <div class="email-lab">
    <div class="email-preview-grid">
      <section
        v-for="variant in templates"
        :key="variant.id"
        class="email-preview"
      >
        <div class="email-preview__label">
          <h2>{{ variant.title }}</h2>
          <p>{{ variant.description }}</p>
        </div>

        <article class="email-canvas" :class="{ 'has-hero': variant.showHero }">
          <div class="email-card">
            <div class="email-brand">
              <img
                class="email-brand__crest"
                :src="logoMain"
                :alt="t('email.brand.crest_alt')"
              />
              <div class="email-brand__wordmark">
                <span>{{ t('email.brand.wordmark') }}</span>
                <span>{{ t('email.brand.subtitle') }}</span>
              </div>
            </div>

            <h1 class="email-title">{{ t('email.title') }}</h1>

            <div v-if="variant.showHero" class="email-hero">
              <img :src="heroImage" :alt="t('email.hero_alt')" />
              <div class="email-hero__warning">
                <span v-for="(label, index) in warningItems" :key="label">
                  {{ label }}
                  <span
                    v-if="index === 0"
                    class="email-hero__separator"
                    aria-hidden="true"
                  />
                </span>
                <span class="email-hero__icon" aria-hidden="true">
                  <svg viewBox="0 0 36 36">
                    <circle cx="18" cy="18" r="16" />
                    <line x1="10" y1="26" x2="26" y2="10" />
                  </svg>
                </span>
              </div>
            </div>

            <div class="email-body">
              <p v-for="(paragraph, index) in paragraphs" :key="index">
                {{ paragraph.text }}
                <a
                  v-if="paragraph.link"
                  :href="paragraph.link.href"
                  target="_blank"
                  rel="noopener"
                >
                  {{ paragraph.link.label }}
                </a>
              </p>
            </div>

            <button type="button" class="email-cta">{{ t('email.cta') }}</button>

            <footer class="email-footer">
              <div class="email-footer__social">
                <a
                  v-for="link in socialLinks"
                  :key="link.id"
                  :href="link.href"
                  target="_blank"
                  rel="noopener"
                  class="email-social"
                >
                  <svg
                    v-if="link.id === 'facebook'"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path
                      d="M13.5 9.5V7.8c0-.8.2-1.3 1.3-1.3h1.2V4h-1.9c-2.3 0-3.3 1.2-3.3 3.2v2.3H8.5V12h2.3v8h2.7v-8h2.1l.3-2.5h-2.4z"
                    />
                  </svg>
                  <svg
                    v-else-if="link.id === 'instagram'"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path
                      d="M17 4H7a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3V7a3 3 0 0 0-3-3zm1.5 13a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 17V7A1.5 1.5 0 0 1 7 5.5h10A1.5 1.5 0 0 1 18.5 7z"
                    />
                    <circle cx="16.5" cy="7.5" r="1" />
                    <circle cx="12" cy="12" r="3.5" />
                  </svg>
                  <svg
                    v-else
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path
                      d="M3.5 6.5v11l7.5-5.5zM11.5 12l9-5.5v11z"
                    />
                  </svg>
                </a>
              </div>

              <div class="email-footer__brand">
                <img :src="logoMain" :alt="t('email.brand.mark_alt')" />
                <div>
                  <p>{{ t('email.brand.wordmark') }}</p>
                  <p>{{ t('email.brand.subtitle') }}</p>
                </div>
              </div>
              <p class="email-footer__legal">
                {{ t('email.legal') }}
              </p>
            </footer>
          </div>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;600;700&family=Noto+Serif+TC:wght@600;700&display=swap');

:deep(body) {
  font-family: 'Noto Sans TC', 'Noto Sans', -apple-system, BlinkMacSystemFont,
    'Segoe UI', sans-serif;
}

.email-lab {
  min-height: 100vh;
  padding: 32px clamp(16px, 4vw, 48px) 64px;
  background: #f4f6fb;
}

.email-preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 32px;
}

.email-preview__label {
  margin-bottom: 16px;
  text-align: center;
}

.email-preview__label h2 {
  margin: 0;
  font-size: 20px;
  color: #0d223d;
}

.email-preview__label p {
  margin: 6px 0 0;
  color: #6b7287;
  font-size: 14px;
}

.email-canvas {
  display: flex;
  justify-content: center;
  background: linear-gradient(180deg, #f9fbff 0%, #eef2f8 100%);
  border-radius: 24px;
  padding: 32px 24px;
  min-height: 100%;
  box-shadow: 0 10px 24px rgba(13, 35, 56, 0.1);
}

.email-card {
  width: min(640px, 100%);
  background: #ffffff;
  border-radius: 32px;
  padding: clamp(32px, 6vw, 48px);
  box-shadow: 0 7px 20px rgba(8, 20, 40, 0.06);
}

.email-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: center;
}

.email-brand__crest {
  width: 64px;
  height: 64px;
  object-fit: contain;
  border-radius: 12px;
  background: #fff;
}

.email-brand__wordmark {
  display: flex;
  flex-direction: column;
  align-items: center;
  font-family: 'Noto Serif TC', 'Noto Sans TC', serif;
  letter-spacing: 0.28em;
  color: #0f2446;
  font-weight: 600;
  font-size: 13px;
}

.email-brand__wordmark span:first-child {
  letter-spacing: 0.48em;
  font-size: 14px;
}

.email-title {
  margin: 28px 0 24px;
  font-size: clamp(26px, 4vw, 34px);
  font-family: 'Noto Serif TC', 'Noto Sans TC', serif;
  color: #10254b;
}

.email-hero {
  border-radius: 16px;
  overflow: hidden;
  margin-bottom: 28px;
  border: 1px solid #e5e7ef;
}

.email-hero img {
  display: block;
  width: 100%;
  height: auto;
}

.email-hero__warning {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: #f1f1f4;
  color: #585e70;
  font-size: 14px;
  padding: 10px 16px;
  font-weight: 500;
}

.email-hero__separator {
  width: 24px;
  height: 2px;
  background: rgba(0, 0, 0, 0.2);
  display: inline-flex;
  margin: 0 8px;
}

.email-hero__icon {
  width: 32px;
  height: 32px;
  color: #b91515;
}

.email-hero__icon svg {
  width: 100%;
  height: 100%;
  fill: none;
  stroke: currentColor;
  stroke-width: 3;
}

.email-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  font-size: 15px;
  line-height: 1.9;
  color: #182842;
}

.email-body a {
  color: #0f54c7;
  text-decoration: none;
  font-weight: 600;
}

.email-body a:hover {
  text-decoration: underline;
}

.email-cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: #55b77f;
  color: #fff;
  font-weight: 600;
  font-size: 16px;
  padding: 14px 48px;
  border-radius: 999px;
  margin: 28px auto 32px;
  box-shadow: 0 8px 18px rgba(85, 183, 127, 0.2);
}

.email-footer {
  padding: 28px 24px;
  border-radius: 20px;
  background: #f5f7fc;
  text-align: center;
}

.email-footer__social {
  display: flex;
  justify-content: center;
  gap: 16px;
  margin-bottom: 20px;
}

.email-social {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  border: 1px solid #d9deeb;
  display: grid;
  place-items: center;
  background: #fff;
  color: #142c4a;
}

.email-social svg {
  width: 22px;
  height: 22px;
  fill: currentColor;
}

.email-footer__brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #22324e;
  font-weight: 600;
}

.email-footer__brand img {
  width: 48px;
  height: 48px;
  object-fit: contain;
  border-radius: 10px;
  background: #fff;
}

.email-footer__brand p {
  margin: 0;
  letter-spacing: 0.32em;
}

.email-footer__legal {
  margin: 12px 0 0;
  font-size: 13px;
  color: #7b8090;
}

@media (max-width: 480px) {
  .email-card {
    padding: 28px 22px 36px;
    border-radius: 28px;
  }

  .email-hero__warning {
    flex-direction: column;
    gap: 8px;
  }

  .email-hero__separator {
    display: none;
  }

  .email-footer {
    padding: 24px 18px;
  }

  .email-footer__brand {
    flex-direction: column;
  }
}
</style>
