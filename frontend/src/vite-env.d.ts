/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** When 'true', enables PoC test mode (one-click persona login). See src/config.ts. */
  readonly VITE_TEST_MODE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
