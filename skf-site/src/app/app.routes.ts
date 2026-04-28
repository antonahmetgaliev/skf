import { Routes } from '@angular/router';
import { adminGuard } from './guards/admin.guard';
import { AdminComponent } from './pages/admin/admin.component';
import { BwpLicenseComponent } from './pages/bwp-license/bwp-license.component';
import { DriverProfileComponent } from './pages/driver-profile/driver-profile.component';
import { DriversListComponent } from './pages/drivers-list/drivers-list.component';
import { HomeVisitComponent } from './pages/home-visit/home-visit.component';
import { ChampionshipsComponent } from './pages/championships/championships.component';
import { IncidentsComponent } from './pages/incidents/incidents.component';
import { ProfileComponent } from './pages/profile/profile.component';
import { RaceResultsComponent } from './pages/race-results/race-results.component';
import { SkfHistoryComponent } from './pages/skf-history/skf-history.component';
import { CalendarComponent } from './pages/calendar/calendar.component';
import { MediaComponent } from './pages/media/media.component';
import { RegulationsComponent } from './pages/regulations/regulations.component';
import { RegulationsIracingLeagueComponent } from './pages/regulations/iracing-league/iracing-league.component';
import { RegulationsNightfallGteComponent } from './pages/regulations/nightfall-gte/nightfall-gte.component';
import { RegulationsThunderTrucksComponent } from './pages/regulations/thunder-trucks/thunder-trucks.component';
import { RegulationsNascarGeneralComponent } from './pages/regulations/nascar-general/nascar-general.component';

export const appRoutes: Routes = [
  { path: '', component: HomeVisitComponent, title: 'Home | SKF Racing Hub' },
  { path: 'home', component: HomeVisitComponent, title: 'Home | SKF Racing Hub' },
  { path: 'bwp-license', component: BwpLicenseComponent, title: 'BWP License | SKF Racing Hub' },
  { path: 'standings', pathMatch: 'full', redirectTo: 'championships' },
  { path: 'championship-standings', pathMatch: 'full', redirectTo: 'championships' },
  { path: 'championships', component: ChampionshipsComponent, title: 'Championships | SKF Racing Hub' },
  { path: 'skf-history', component: SkfHistoryComponent, title: 'SKF History | SKF Racing Hub' },
  { path: 'race-results', component: RaceResultsComponent, title: 'Race Results | SKF Racing Hub' },
  { path: 'calendar', component: CalendarComponent, title: 'Calendar | SKF Racing Hub' },
  { path: 'regulations', component: RegulationsComponent, title: 'General Regulations | SKF Racing Hub' },
  { path: 'regulations/nascar-general', component: RegulationsNascarGeneralComponent, title: 'NASCAR General Regulations | SKF Racing Hub' },
  { path: 'regulations/iracing-league', component: RegulationsIracingLeagueComponent, title: 'SKF iRacing League Regulations | SKF Racing Hub' },
  { path: 'regulations/nightfall-gte', component: RegulationsNightfallGteComponent, title: 'SKF Nightfall GTE Championship Regulations | SKF Racing Hub' },
  { path: 'regulations/thunder-trucks', component: RegulationsThunderTrucksComponent, title: 'SKF Thunder Truck Series Regulations | SKF Racing Hub' },
  { path: 'media', component: MediaComponent, title: 'Media | SKF Racing Hub' },
  { path: 'profile', component: ProfileComponent, title: 'Profile | SKF Racing Hub' },
  { path: 'drivers', component: DriversListComponent, title: 'Drivers | SKF Racing Hub' },
  { path: 'drivers/:id', component: DriverProfileComponent, title: 'Driver Profile | SKF Racing Hub' },
  { path: 'incidents', component: IncidentsComponent, title: 'Incidents | SKF Racing Hub' },
  { path: 'admin/users', pathMatch: 'full', redirectTo: 'admin' },
  { path: 'admin', component: AdminComponent, canActivate: [adminGuard], title: 'Admin | SKF Racing Hub' },
  { path: '**', redirectTo: '' }
];
