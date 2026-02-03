import { HttpErrorResponse } from '@angular/common/http';
import { Component, ElementRef, ViewChild, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  ChampionshipDetails,
  ChampionshipListItem,
  SimgridApiService,
  StandingEntry,
  StandingRace
} from '../../services/simgrid-api.service';

interface CachedStandingsData {
  details: ChampionshipDetails;
  entries: StandingEntry[];
  races: StandingRace[];
  fetchedAt: Date;
}

@Component({
  selector: 'app-championship-standings',
  templateUrl: './championship-standings.component.html',
  styleUrl: './championship-standings.component.scss'
})
export class ChampionshipStandingsComponent {
  private readonly api = inject(SimgridApiService);
  private readonly cacheTtlMs = 60000;
  private readonly standingsCache = new Map<number, CachedStandingsData>();
  private standingsLoadToken = 0;
  private championshipsLoadToken = 0;
  private readonly exportWidth = 1920;
  private readonly exportHeight = 1080;
  private readonly dateFormatter = new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  });

  @ViewChild('standingsExportCanvas')
  private standingsExportCanvas?: ElementRef<HTMLCanvasElement>;

  readonly championships = signal<ChampionshipListItem[]>([]);
  readonly selectedChampionshipId = signal<number | null>(null);
  readonly selectedChampionship = signal<ChampionshipDetails | null>(null);
  readonly standings = signal<StandingEntry[]>([]);
  readonly races = signal<StandingRace[]>([]);
  readonly loadingChampionships = signal(false);
  readonly loadingStandings = signal(false);
  readonly exportPreviewOpen = signal(false);
  readonly exportRendering = signal(false);
  readonly errorMessage = signal('');
  readonly infoMessage = signal('');
  readonly lastUpdated = signal<Date | null>(null);

  constructor() {
    void this.loadChampionships();
  }

  async loadChampionships(): Promise<void> {
    const token = ++this.championshipsLoadToken;
    this.loadingChampionships.set(true);
    this.errorMessage.set('');
    this.infoMessage.set('');

    try {
      const list = await firstValueFrom(this.api.getChampionships());
      if (token !== this.championshipsLoadToken) {
        return;
      }

      const sorted = [...list].sort((a, b) => b.id - a.id);
      this.championships.set(sorted);

      if (sorted.length === 0) {
        this.selectedChampionshipId.set(null);
        this.selectedChampionship.set(null);
        this.standings.set([]);
        this.races.set([]);
        return;
      }

      const currentSelectedId = this.selectedChampionshipId();
      const selectedId =
        currentSelectedId !== null && sorted.some((item) => item.id === currentSelectedId)
          ? currentSelectedId
          : sorted[0].id;

      this.selectedChampionshipId.set(selectedId);
      await this.loadStandings(selectedId);
    } catch (error) {
      if (token !== this.championshipsLoadToken) {
        return;
      }
      this.errorMessage.set(this.toErrorMessage(error));
      this.championships.set([]);
      this.selectedChampionship.set(null);
      this.standings.set([]);
      this.races.set([]);
    } finally {
      if (token === this.championshipsLoadToken) {
        this.loadingChampionships.set(false);
      }
    }
  }

  selectChampionship(championshipId: number): void {
    if (this.selectedChampionshipId() === championshipId && this.standings().length > 0) {
      return;
    }
    this.selectedChampionshipId.set(championshipId);
    void this.loadStandings(championshipId);
  }

  refreshSelectedChampionship(): void {
    const championshipId = this.selectedChampionshipId();
    if (championshipId === null) {
      return;
    }
    void this.loadStandings(championshipId, true);
  }

  openStandingsExportPreview(): void {
    if (this.loadingStandings() || !this.selectedChampionship() || this.standings().length === 0) {
      return;
    }

    this.exportPreviewOpen.set(true);
    setTimeout(() => {
      void this.renderStandingsExportPreview();
    }, 0);
  }

  closeStandingsExportPreview(): void {
    this.exportPreviewOpen.set(false);
  }

  downloadStandingsExportJpg(): void {
    const canvas = this.standingsExportCanvas?.nativeElement;
    if (!canvas) {
      return;
    }

    const championshipName = this.selectedChampionship()?.name ?? 'championship-standings';
    const fileName = `${this.toSlug(championshipName)}-standings.jpg`;

    canvas.toBlob((blob) => {
      if (!blob) {
        return;
      }

      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(url);
    }, 'image/jpeg', 0.93);
  }

  getPosition(entry: StandingEntry, index: number): number {
    return entry.position ?? index + 1;
  }

  getOverallColspan(): number {
    return 5 + this.races().length;
  }

  formatDate(value: string | null): string {
    if (!value) {
      return '-';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return this.dateFormatter.format(parsed);
  }

  formatNumber(value: number): string {
    const isWhole = Math.abs(value % 1) < 0.00001;
    return isWhole ? String(Math.trunc(value)) : value.toFixed(1);
  }

  getRaceLabel(index: number): string {
    return `R${index + 1}`;
  }

  getRaceTitle(race: StandingRace, index: number): string {
    const datePart = race.startsAt ? this.formatDate(race.startsAt) : 'TBD';
    return `${this.getRaceLabel(index)} - ${race.displayName} (${datePart})`;
  }

  formatRacePosition(entry: StandingEntry, race: StandingRace, raceIndex: number): string {
    const result = this.getRaceResult(entry, race, raceIndex);
    if (!result || result.position === null) {
      return '-';
    }

    return String(result.position);
  }

  private getRaceResult(
    entry: StandingEntry,
    race: StandingRace,
    raceIndex: number
  ): { points: number | null; position: number | null } | null {
    const byRaceId = entry.raceResults.find(
      (item) => item.raceId !== null && item.raceId === race.id
    );
    if (byRaceId) {
      return byRaceId;
    }

    return entry.raceResults.find((item) => item.raceIndex === raceIndex) ?? null;
  }

  private async renderStandingsExportPreview(): Promise<void> {
    const canvas = this.standingsExportCanvas?.nativeElement;
    const championship = this.selectedChampionship();
    if (!canvas || !championship) {
      return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      return;
    }

    this.exportRendering.set(true);

    try {
      canvas.width = this.exportWidth;
      canvas.height = this.exportHeight;

      const [backgroundImage, logoImage] = await Promise.all([
        this.loadImage('skf-background.png'),
        this.loadImage('skf-logo.png')
      ]);

      const width = canvas.width;
      const height = canvas.height;

      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = '#090d14';
      ctx.fillRect(0, 0, width, height);

      if (backgroundImage) {
        ctx.save();
        ctx.globalAlpha = 0.26;
        ctx.drawImage(backgroundImage, 0, 0, width, height);
        ctx.restore();
      }

      const shadowGradient = ctx.createLinearGradient(0, 0, width, height);
      shadowGradient.addColorStop(0, 'rgba(8, 10, 15, 0.3)');
      shadowGradient.addColorStop(1, 'rgba(8, 10, 15, 0.86)');
      ctx.fillStyle = shadowGradient;
      ctx.fillRect(0, 0, width, height);

      ctx.fillStyle = 'rgba(245, 189, 29, 0.92)';
      ctx.beginPath();
      ctx.moveTo(0, 110);
      ctx.lineTo(940, 40);
      ctx.lineTo(880, 260);
      ctx.lineTo(0, 400);
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = 'rgba(245, 189, 29, 0.82)';
      ctx.beginPath();
      ctx.moveTo(0, 760);
      ctx.lineTo(1120, 500);
      ctx.lineTo(1025, 865);
      ctx.lineTo(0, 1030);
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = '#12161f';
      ctx.font = '700 34px "Bahnschrift", "Segoe UI", sans-serif';
      ctx.fillText('SKF RACING HUB', 76, 88);

      ctx.fillStyle = '#f7f9fe';
      ctx.font = '900 132px "Bahnschrift", "Arial Black", sans-serif';
      ctx.fillText('STANDINGS', 70, 220);

      ctx.fillStyle = '#f5be2d';
      ctx.font = '800 58px "Bahnschrift", "Segoe UI", sans-serif';
      const titleBottomY = this.drawWrappedText(
        ctx,
        championship.name.toUpperCase(),
        80,
        286,
        1140,
        64,
        2
      );

      ctx.fillStyle = 'rgba(245, 248, 255, 0.9)';
      ctx.font = '600 30px "Segoe UI", sans-serif';
      const refreshed = this.lastUpdated();
      const refreshedText = refreshed ? refreshed.toLocaleString() : 'now';
      ctx.fillText(
        `${this.standings().length} drivers - Updated ${refreshedText}`,
        80,
        titleBottomY + 50
      );

      if (logoImage) {
        const logoSize = 158;
        const logoX = width - logoSize - 92;
        const logoY = 42;
        const radius = logoSize / 2;

        ctx.save();
        ctx.beginPath();
        ctx.arc(logoX + radius, logoY + radius, radius, 0, Math.PI * 2);
        ctx.closePath();
        ctx.clip();
        ctx.drawImage(logoImage, logoX, logoY, logoSize, logoSize);
        ctx.restore();

        ctx.strokeStyle = 'rgba(255, 255, 255, 0.55)';
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.arc(logoX + radius, logoY + radius, radius - 2, 0, Math.PI * 2);
        ctx.stroke();
      }

      const panelX = 60;
      const panelY = 320;
      const panelWidth = width - panelX * 2;
      const panelHeight = height - panelY - 56;

      ctx.fillStyle = 'rgba(8, 11, 18, 0.86)';
      this.fillRoundedRect(ctx, panelX, panelY, panelWidth, panelHeight, 24);
      ctx.strokeStyle = 'rgba(245, 189, 29, 0.45)';
      ctx.lineWidth = 2;
      this.strokeRoundedRect(ctx, panelX, panelY, panelWidth, panelHeight, 24);

      ctx.fillStyle = '#f5be2d';
      ctx.font = '800 34px "Bahnschrift", "Segoe UI", sans-serif';
      ctx.fillText('OVERALL STANDINGS', panelX + 24, panelY + 52);

      const standings = this.standings();
      const splitIndex = Math.ceil(standings.length / 2);
      const leftEntries = standings.slice(0, splitIndex);
      const rightEntries = standings.slice(splitIndex);

      const columnsGap = 26;
      const columnsX = panelX + 22;
      const columnsY = panelY + 72;
      const columnsHeight = panelHeight - 92;
      const columnWidth = (panelWidth - 44 - columnsGap) / 2;

      this.drawStandingsColumn(ctx, columnsX, columnsY, columnWidth, columnsHeight, leftEntries, 0);
      this.drawStandingsColumn(
        ctx,
        columnsX + columnWidth + columnsGap,
        columnsY,
        columnWidth,
        columnsHeight,
        rightEntries,
        splitIndex
      );

      ctx.fillStyle = 'rgba(245, 248, 255, 0.65)';
      ctx.font = '500 22px "Segoe UI", sans-serif';
      ctx.fillText('Generated by SKF Racing Hub Control Desk', panelX + 24, height - 26);
    } finally {
      this.exportRendering.set(false);
    }
  }

  private drawStandingsColumn(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    entries: StandingEntry[],
    globalOffset: number
  ): void {
    const races = this.races().slice(0, 6);
    const raceCount = races.length;

    const headerHeight = 42;
    const rowCount = Math.max(entries.length, 1);
    const rowHeight = Math.max(28, Math.floor((height - headerHeight - 6) / rowCount));

    const innerPadding = 12;
    const posWidth = 56;
    const scoreWidth = 82;
    let raceAreaWidth = raceCount > 0 ? Math.min(260, width * 0.33) : 0;
    let driverWidth = width - innerPadding * 2 - posWidth - scoreWidth - raceAreaWidth - 26;

    if (driverWidth < 165 && raceCount > 0) {
      raceAreaWidth = Math.max(raceCount * 34, raceAreaWidth - (165 - driverWidth));
      driverWidth = width - innerPadding * 2 - posWidth - scoreWidth - raceAreaWidth - 26;
    }

    const posX = x + innerPadding;
    const driverX = posX + posWidth + 8;
    const scoreX = driverX + driverWidth + 10;
    const raceX = scoreX + scoreWidth + 8;
    const raceCellWidth = raceCount > 0 ? raceAreaWidth / raceCount : 0;

    ctx.fillStyle = 'rgba(255, 255, 255, 0.055)';
    this.fillRoundedRect(ctx, x, y, width, height, 16);

    ctx.fillStyle = 'rgba(255, 255, 255, 0.11)';
    this.fillRoundedRect(ctx, x, y, width, headerHeight, 12);

    ctx.fillStyle = 'rgba(245, 248, 255, 0.95)';
    ctx.font = '700 16px "Bahnschrift", "Segoe UI", sans-serif';
    ctx.fillText('POS', posX + 4, y + 28);
    ctx.fillText('DRIVER', driverX, y + 28);

    this.drawCenteredText(ctx, 'SCORE', scoreX + scoreWidth / 2, y + 28);

    races.forEach((_, raceIndex) => {
      this.drawCenteredText(
        ctx,
        this.getRaceLabel(raceIndex),
        raceX + raceCellWidth * raceIndex + raceCellWidth / 2,
        y + 28
      );
    });

    entries.forEach((entry, rowIndex) => {
      const rowY = y + headerHeight + rowIndex * rowHeight;
      ctx.fillStyle = rowIndex % 2 === 0 ? 'rgba(255, 255, 255, 0.02)' : 'rgba(255, 255, 255, 0.05)';
      ctx.fillRect(x + 1, rowY, width - 2, rowHeight);

      const rank = this.getPosition(entry, globalOffset + rowIndex);
      const badgeColor =
        rank === 1
          ? '#f5be2d'
          : rank === 2
            ? '#cfd7e1'
            : rank === 3
              ? '#d19a5c'
              : '#242b39';

      const badgeX = posX;
      const badgeY = rowY + 5;
      const badgeWidth = posWidth - 6;
      const badgeHeight = rowHeight - 10;

      ctx.fillStyle = badgeColor;
      this.fillRoundedRect(ctx, badgeX, badgeY, badgeWidth, badgeHeight, 9);

      ctx.fillStyle = rank <= 3 ? '#131722' : '#f4f7ff';
      ctx.font = '700 18px "Segoe UI", sans-serif';
      this.drawCenteredText(ctx, String(rank), badgeX + badgeWidth / 2, badgeY + badgeHeight * 0.66);

      ctx.fillStyle = '#f7faff';
      ctx.font = '600 20px "Segoe UI", sans-serif';
      const driverName = this.truncateText(ctx, entry.displayName, driverWidth - 4);
      ctx.fillText(driverName, driverX, rowY + rowHeight * 0.68);

      ctx.fillStyle = '#f5be2d';
      ctx.font = '700 19px "Segoe UI", sans-serif';
      this.drawCenteredText(
        ctx,
        this.formatNumber(entry.score),
        scoreX + scoreWidth / 2,
        rowY + rowHeight * 0.67
      );

      races.forEach((race, raceIndex) => {
        const value = this.formatRacePosition(entry, race, raceIndex);
        const numericValue = Number(value);
        const isPodium = Number.isFinite(numericValue) && numericValue > 0 && numericValue <= 3;
        ctx.fillStyle = isPodium ? '#f5be2d' : 'rgba(243, 247, 255, 0.95)';
        ctx.font = '700 18px "Segoe UI", sans-serif';

        this.drawCenteredText(
          ctx,
          value,
          raceX + raceCellWidth * raceIndex + raceCellWidth / 2,
          rowY + rowHeight * 0.67
        );
      });
    });
  }

  private drawWrappedText(
    ctx: CanvasRenderingContext2D,
    text: string,
    x: number,
    y: number,
    maxWidth: number,
    lineHeight: number,
    maxLines: number
  ): number {
    const words = text.split(/\s+/).filter((word) => word.length > 0);
    let line = '';
    let currentY = y;
    let lineIndex = 0;

    for (let i = 0; i < words.length; i += 1) {
      const testLine = line.length > 0 ? `${line} ${words[i]}` : words[i];
      const testWidth = ctx.measureText(testLine).width;
      const isLastWord = i === words.length - 1;

      if (testWidth > maxWidth && line.length > 0) {
        ctx.fillText(line, x, currentY);
        lineIndex += 1;
        if (lineIndex >= maxLines) {
          return currentY;
        }
        currentY += lineHeight;
        line = words[i];
      } else {
        line = testLine;
      }

      if (isLastWord) {
        if (lineIndex >= maxLines) {
          return currentY;
        }
        const finalLine = lineIndex === maxLines - 1 ? this.truncateText(ctx, line, maxWidth) : line;
        ctx.fillText(finalLine, x, currentY);
      }
    }

    return currentY;
  }

  private drawCenteredText(
    ctx: CanvasRenderingContext2D,
    text: string,
    centerX: number,
    baselineY: number
  ): void {
    const width = ctx.measureText(text).width;
    ctx.fillText(text, centerX - width / 2, baselineY);
  }

  private truncateText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
    if (ctx.measureText(text).width <= maxWidth) {
      return text;
    }

    let shortened = text;
    while (shortened.length > 1 && ctx.measureText(`${shortened}...`).width > maxWidth) {
      shortened = shortened.slice(0, -1);
    }

    return `${shortened}...`;
  }

  private fillRoundedRect(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    radius: number
  ): void {
    const clippedRadius = Math.min(radius, width / 2, height / 2);

    ctx.beginPath();
    ctx.moveTo(x + clippedRadius, y);
    ctx.lineTo(x + width - clippedRadius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + clippedRadius);
    ctx.lineTo(x + width, y + height - clippedRadius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - clippedRadius, y + height);
    ctx.lineTo(x + clippedRadius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - clippedRadius);
    ctx.lineTo(x, y + clippedRadius);
    ctx.quadraticCurveTo(x, y, x + clippedRadius, y);
    ctx.closePath();
    ctx.fill();
  }

  private strokeRoundedRect(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    radius: number
  ): void {
    const clippedRadius = Math.min(radius, width / 2, height / 2);

    ctx.beginPath();
    ctx.moveTo(x + clippedRadius, y);
    ctx.lineTo(x + width - clippedRadius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + clippedRadius);
    ctx.lineTo(x + width, y + height - clippedRadius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - clippedRadius, y + height);
    ctx.lineTo(x + clippedRadius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - clippedRadius);
    ctx.lineTo(x, y + clippedRadius);
    ctx.quadraticCurveTo(x, y, x + clippedRadius, y);
    ctx.closePath();
    ctx.stroke();
  }

  private async loadImage(src: string): Promise<HTMLImageElement | null> {
    return new Promise((resolve) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => resolve(null);
      image.src = src;
    });
  }

  private toSlug(value: string): string {
    return value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 80);
  }

  private async loadStandings(championshipId: number, force = false): Promise<void> {
    const token = ++this.standingsLoadToken;
    const cached = this.standingsCache.get(championshipId);

    if (!force && cached && !this.isCacheExpired(cached)) {
      this.errorMessage.set('');
      this.infoMessage.set('');
      this.selectedChampionship.set(cached.details);
      this.standings.set(cached.entries);
      this.races.set(cached.races);
      this.lastUpdated.set(cached.fetchedAt);
      return;
    }

    this.loadingStandings.set(true);
    this.errorMessage.set('');
    this.infoMessage.set('');

    try {
      const detailsPromise = cached
        ? Promise.resolve(cached.details)
        : firstValueFrom(this.api.getChampionshipById(championshipId));

      const [details, standingsData] = await Promise.all([
        detailsPromise,
        firstValueFrom(this.api.getChampionshipStandings(championshipId))
      ]);

      if (token !== this.standingsLoadToken) {
        return;
      }

      const fetchedAt = new Date();
      this.selectedChampionship.set(details);
      this.standings.set(standingsData.entries);
      this.races.set(standingsData.races);
      this.lastUpdated.set(fetchedAt);
      this.standingsCache.set(championshipId, {
        details,
        entries: standingsData.entries,
        races: standingsData.races,
        fetchedAt
      });

      if (this.exportPreviewOpen()) {
        setTimeout(() => {
          void this.renderStandingsExportPreview();
        }, 0);
      }
    } catch (error) {
      if (token !== this.standingsLoadToken) {
        return;
      }

      if (this.isRateLimitError(error) && cached) {
        this.selectedChampionship.set(cached.details);
        this.standings.set(cached.entries);
        this.races.set(cached.races);
        this.lastUpdated.set(cached.fetchedAt);
        this.errorMessage.set('');
        this.infoMessage.set(this.toRateLimitCacheMessage(error, cached.fetchedAt));
        return;
      }

      this.errorMessage.set(this.toErrorMessage(error));
      this.selectedChampionship.set(null);
      this.standings.set([]);
      this.races.set([]);
    } finally {
      if (token === this.standingsLoadToken) {
        this.loadingStandings.set(false);
      }
    }
  }

  private isCacheExpired(cache: CachedStandingsData): boolean {
    return Date.now() - cache.fetchedAt.getTime() > this.cacheTtlMs;
  }

  private isRateLimitError(error: unknown): error is HttpErrorResponse {
    return error instanceof HttpErrorResponse && error.status === 429;
  }

  private toRateLimitCacheMessage(error: HttpErrorResponse, cachedAt: Date): string {
    const reason = this.extractErrorReason(error) ?? 'Minute rate limit exceeded';
    return `${reason}. Showing cached data from ${cachedAt.toLocaleTimeString()}. Try Refresh in about 1 minute.`;
  }

  private extractErrorReason(error: HttpErrorResponse): string | null {
    const payload = error.error;
    if (payload && typeof payload === 'object') {
      const candidate = (payload as { error?: unknown }).error;
      if (typeof candidate === 'string' && candidate.trim().length > 0) {
        return candidate;
      }
    }

    if (typeof payload === 'string' && payload.trim().length > 0) {
      return payload;
    }

    return null;
  }

  private toErrorMessage(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      if (error.status === 0) {
        return 'Unable to reach The SimGrid API. If you run locally, use ng serve with the proxy config.';
      }
      if (error.status === 200) {
        return 'API returned HTML instead of JSON (proxy not applied). Restart `npm start` and retry.';
      }
      if (error.status === 429) {
        const reason = this.extractErrorReason(error) ?? 'Minute rate limit exceeded';
        return `${reason}. Please wait about 1 minute and try again.`;
      }
      return `API request failed (${error.status}).`;
    }
    return 'Failed to load standings data.';
  }
}
