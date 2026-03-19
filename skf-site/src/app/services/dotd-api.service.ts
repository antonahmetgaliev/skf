import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface DotdCandidateOut {
  id: string;
  simgridDriverId: number | null;
  driverName: string;
  championshipPosition: number | null;
  voteCount: number | null;
}

export interface DotdPollOut {
  id: string;
  championshipId: number;
  championshipName: string;
  raceId: number | null;
  raceName: string;
  createdAt: string;
  closesAt: string;
  isOpen: boolean;
  candidates: DotdCandidateOut[];
  hasVoted: boolean;
  myVoteCandidateId: string | null;
  totalVotes: number;
}

export interface DotdCandidateIn {
  simgridDriverId?: number | null;
  driverName: string;
  championshipPosition?: number | null;
}

export interface DotdPollCreate {
  championshipId: number;
  championshipName: string;
  raceId?: number | null;
  raceName: string;
  closesAt: string;
  candidates: DotdCandidateIn[];
}

@Injectable({ providedIn: 'root' })
export class DotdApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/dotd';

  getPolls(): Observable<DotdPollOut[]> {
    return this.http.get<DotdPollOut[]>(`${this.base}/polls`);
  }

  createPoll(payload: DotdPollCreate): Observable<DotdPollOut> {
    return this.http.post<DotdPollOut>(`${this.base}/polls`, payload);
  }

  closePoll(pollId: string): Observable<DotdPollOut> {
    return this.http.patch<DotdPollOut>(`${this.base}/polls/${pollId}/close`, {});
  }

  vote(pollId: string, candidateId: string): Observable<DotdPollOut> {
    return this.http.post<DotdPollOut>(
      `${this.base}/polls/${pollId}/vote`,
      null,
      { params: { candidate_id: candidateId } },
    );
  }

  deletePoll(pollId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/polls/${pollId}`);
  }
}
