-- CreateTable
CREATE TABLE "branches" (
    "branch_id" TEXT NOT NULL,
    "branch_code" TEXT,
    "branch_name" TEXT,
    "branch_type" TEXT,
    "address" TEXT,
    "city" TEXT,
    "state" TEXT,
    "country" TEXT,
    "postal_code" TEXT,
    "geographic_zone" TEXT,
    "phone" TEXT,
    "email" TEXT,
    "opening_time" TEXT,
    "closing_time" TEXT,
    "has_atms" BOOLEAN,
    "atm_count" INTEGER,
    "has_teller_windows" BOOLEAN,
    "teller_window_count" INTEGER,
    "latitude" DOUBLE PRECISION,
    "longitude" DOUBLE PRECISION,
    "branch_opening_date" DATE,
    "branch_status" TEXT,

    CONSTRAINT "branches_pkey" PRIMARY KEY ("branch_id")
);

-- CreateTable
CREATE TABLE "customers" (
    "customer_id" TEXT NOT NULL,
    "document_number" TEXT,
    "document_type" TEXT,
    "first_name" TEXT,
    "last_name" TEXT,
    "date_of_birth" DATE,
    "gender" TEXT,
    "email" TEXT,
    "mobile_phone" TEXT,
    "landline_phone" TEXT,
    "address" TEXT,
    "city" TEXT,
    "state" TEXT,
    "country" TEXT,
    "postal_code" TEXT,
    "detected_accent" TEXT,
    "segment" TEXT,
    "credit_score" DOUBLE PRECISION,
    "estimated_monthly_income" DECIMAL(20,2),
    "occupation" TEXT,
    "marital_status" TEXT,
    "education_level" TEXT,
    "registration_date" TIMESTAMP(6),
    "registration_branch_id" TEXT,
    "customer_status" TEXT,
    "last_updated" TIMESTAMP(6),
    "accepts_marketing" BOOLEAN,

    CONSTRAINT "customers_pkey" PRIMARY KEY ("customer_id")
);

-- CreateTable
CREATE TABLE "products" (
    "product_id" TEXT NOT NULL,
    "customer_id" TEXT NOT NULL,
    "product_type" TEXT NOT NULL,
    "product_number" TEXT,
    "currency" TEXT NOT NULL,
    "current_balance" DECIMAL(20,2),
    "credit_limit" DECIMAL(20,2),
    "interest_rate" DOUBLE PRECISION,
    "opening_date" DATE,
    "expiration_date" DATE,
    "opening_branch_id" TEXT,
    "product_status" TEXT,
    "opening_channel" TEXT,
    "has_linked_app" BOOLEAN,
    "days_past_due" DOUBLE PRECISION,
    "last_transaction_date" TIMESTAMP(6),
    "last_updated" TIMESTAMP(6),

    CONSTRAINT "products_pkey" PRIMARY KEY ("product_id")
);

-- CreateTable
CREATE TABLE "daily_exchange_rates" (
    "date" DATE NOT NULL,
    "source_currency" TEXT NOT NULL,
    "target_currency" TEXT NOT NULL,
    "exchange_rate" DECIMAL(24,10) NOT NULL,
    "buy_rate" DECIMAL(24,10),
    "sell_rate" DECIMAL(24,10),
    "source" TEXT,

    CONSTRAINT "daily_exchange_rates_pkey" PRIMARY KEY ("source_currency","target_currency","date")
);

-- CreateTable
CREATE TABLE "transactions" (
    "transaction_id" TEXT NOT NULL,
    "transaction_date" TIMESTAMP(6) NOT NULL,
    "process_date" DATE,
    "product_id" TEXT,
    "customer_id" TEXT,
    "transaction_type" TEXT,
    "transaction_category" TEXT,
    "amount" DECIMAL(20,2) NOT NULL,
    "currency" TEXT NOT NULL,
    "amount_usd" DECIMAL(20,2),
    "channel" TEXT,
    "branch_id" TEXT,
    "merchant_name" TEXT,
    "merchant_category" TEXT,
    "transaction_country" TEXT,
    "transaction_city" TEXT,
    "transaction_status" TEXT,
    "response_code" TEXT,
    "is_fraud" BOOLEAN,
    "fraud_score" DOUBLE PRECISION,
    "latitude" DOUBLE PRECISION,
    "longitude" DOUBLE PRECISION,
    "origin" TEXT NOT NULL DEFAULT 'historical',
    "payment_method" TEXT,
    "description" TEXT,
    "counterparty" JSONB,
    "related_product_id" TEXT,
    "scheduled_payment_id" TEXT,
    "balance_after" DECIMAL(20,2),

    CONSTRAINT "transactions_pkey" PRIMARY KEY ("transaction_id")
);

-- CreateTable
CREATE TABLE "scheduled_payments" (
    "scheduled_payment_id" TEXT NOT NULL,
    "customer_id" TEXT NOT NULL,
    "product_id" TEXT NOT NULL,
    "payment_method" TEXT NOT NULL,
    "amount" DECIMAL(20,2) NOT NULL,
    "currency" TEXT NOT NULL,
    "destination" JSONB NOT NULL,
    "description" TEXT,
    "frequency" TEXT NOT NULL,
    "next_run_at" TIMESTAMPTZ(6),
    "end_date" DATE,
    "max_executions" INTEGER,
    "executions_count" INTEGER NOT NULL DEFAULT 0,
    "status" TEXT NOT NULL DEFAULT 'active',
    "last_run_at" TIMESTAMPTZ(6),
    "last_transaction_id" TEXT,
    "last_result" TEXT,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,

    CONSTRAINT "scheduled_payments_pkey" PRIMARY KEY ("scheduled_payment_id")
);

-- CreateIndex
CREATE INDEX "customers_email_idx" ON "customers"("email");

-- CreateIndex
CREATE INDEX "customers_document_number_idx" ON "customers"("document_number");

-- CreateIndex
CREATE INDEX "products_customer_id_idx" ON "products"("customer_id");

-- CreateIndex
CREATE INDEX "transactions_customer_id_transaction_date_idx" ON "transactions"("customer_id", "transaction_date" DESC);

-- CreateIndex
CREATE INDEX "transactions_product_id_transaction_date_idx" ON "transactions"("product_id", "transaction_date" DESC);

-- CreateIndex
CREATE INDEX "transactions_scheduled_payment_id_idx" ON "transactions"("scheduled_payment_id");

-- CreateIndex
CREATE INDEX "scheduled_payments_customer_id_idx" ON "scheduled_payments"("customer_id");

-- CreateIndex
CREATE INDEX "scheduled_payments_status_next_run_at_idx" ON "scheduled_payments"("status", "next_run_at");
