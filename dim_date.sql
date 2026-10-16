/* =========================================================
   Tabela kalendarza (DimDate) z polskimi świętami
   i niedzielami handlowymi – zakres od 2024 r.
   SQL Server 2016+ (ISO_WEEK, DATEFROMPARTS, CHOOSE)
   ========================================================= */

-- 1) Funkcja licząca datę Wielkanocy (algorytm Meeusa/Jonesa/Butchera)
CREATE OR ALTER FUNCTION dbo.fn_EasterSunday (@Year INT)
RETURNS DATE
WITH SCHEMABINDING
AS
BEGIN
    DECLARE @a INT = @Year % 19,
            @b INT = @Year / 100,
            @c INT = @Year % 100;
    DECLARE @d INT = @b / 4,
            @e INT = @b % 4,
            @f INT = (@b + 8) / 25;
    DECLARE @g INT = (@b - @f + 1) / 3;
    DECLARE @h INT = (19 * @a + @b - @d - @g + 15) % 30,
            @i INT = @c / 4,
            @k INT = @c % 4;
    DECLARE @l INT = (32 + 2 * @e + 2 * @i - @h - @k) % 7;
    DECLARE @m INT = (@a + 11 * @h + 22 * @l) / 451;

    RETURN DATEFROMPARTS(
        @Year,
        (@h + @l - 7 * @m + 114) / 31,
        ((@h + @l - 7 * @m + 114) % 31) + 1);
END;
GO

-- 2) Tabela
DROP TABLE IF EXISTS dbo.DimDate;

CREATE TABLE dbo.DimDate (
    DateKey          INT           NOT NULL PRIMARY KEY,   -- yyyymmdd, np. 20261016
    [Date]           DATE          NOT NULL UNIQUE,
    [Year]           SMALLINT      NOT NULL,
    [Quarter]        TINYINT       NOT NULL,
    [Month]          TINYINT       NOT NULL,
    MonthName        NVARCHAR(20)  NOT NULL,
    IsoWeek          TINYINT       NOT NULL,               -- numer tygodnia ISO (PL)