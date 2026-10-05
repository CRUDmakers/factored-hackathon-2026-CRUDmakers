-- Linhagem do ETL: um registro por arquivo carregado (manifesto) e o arquivo de origem de cada transação.
CREATE TABLE "etl_files" (
    "file" TEXT NOT NULL,
    "target_table" TEXT NOT NULL,
    "partition_date" DATE,
    "sha256" TEXT NOT NULL,
    "rows_read" INTEGER NOT NULL,
    "rows_loaded" INTEGER NOT NULL,
    "rows_rejected" INTEGER NOT NULL,
    "rejects" JSONB NOT NULL,
    "loaded_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "etl_files_pkey" PRIMARY KEY ("file")
);

ALTER TABLE "transactions" ADD COLUMN "source_file" TEXT;
CREATE INDEX "transactions_source_file_idx" ON "transactions"("source_file");
