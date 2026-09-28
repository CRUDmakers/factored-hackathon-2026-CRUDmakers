-- CreateTable
CREATE TABLE "revoked_sessions" (
    "jti" TEXT NOT NULL,
    "customer_id" TEXT NOT NULL,
    "expires_at" TIMESTAMPTZ(6) NOT NULL,
    "revoked_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "revoked_sessions_pkey" PRIMARY KEY ("jti")
);

-- CreateIndex
CREATE INDEX "revoked_sessions_expires_at_idx" ON "revoked_sessions"("expires_at");
